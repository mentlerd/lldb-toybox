#
# Synthetic/summary providers for various hash table based types
#
# Besides adding support for types not known to LLDB by default, this file will
#  create overrides for libc++ container types too:
#
# Synthetics implemented in this file will display the elements of various containers
#  in _natural order_ (as opposed to the default _iteration order_) when the hashed
#  keys can be converted into simple integral types.
#
# Currently supported types:
# - std::unordered_map
# - std::unordered_set
# - absl::flat_hash_map
# - absl::flat_hash_set
# - absl::node_hash_map
# - absl::node_hash_set
#
# Usage:
# > (lldb) command script import <path-to-this-file>
#

import lldb
import re
import math

def register_category(debugger, name):
	category = debugger.GetCategory(name)

	if not category.IsValid():
		category = debugger.CreateCategory(name)
		category.AddLanguage(lldb.eLanguageTypeC_plus_plus)
		category.SetEnabled(True)

	return category

def register_container_synthetic(category, clazz):
	name_spec = lldb.SBTypeNameSpecifier(clazz.typename_regex, True)

	options = lldb.eTypeOptionNone
	options |= lldb.eTypeOptionCascade
	options |= lldb.eTypeOptionFrontEndWantsDereference

	synthetic = lldb.SBTypeSynthetic.CreateWithClassName(f'{__name__}.{clazz.__name__}')
	synthetic.SetOptions(options)

	summary = lldb.SBTypeSummary.CreateWithScriptCode(f'''
		return {__name__}.{clazz.__name__}(valobj.GetNonSyntheticValue(), internal_dict).get_summary()
	''')
	summary.SetOptions(options)

	category.AddTypeSynthetic(name_spec, synthetic)
	category.AddTypeSummary(name_spec, summary)

def __lldb_init_module(debugger, dict):
	libcxx_overrides = register_category(debugger, "lldb-toybox.libcxx-overrides")

	# LLDB already includes support for these, make them easy to disable just to be safe
	register_container_synthetic(libcxx_overrides, LibCXXHashContainerSynthetic)
	register_container_synthetic(libcxx_overrides, LibCXXHashContainerIteratorSynthetic)

	libcxx = register_category(debugger, "lldb-toybox.libcxx")

	register_container_synthetic(libcxx, LibCXXHashContainerNodeSynthetic)

	abseil = register_category(debugger, "lldb-toybox.abseil")

	register_container_synthetic(abseil, AbseilHashContainerSynthetic)
	register_container_synthetic(abseil, AbseilHashContainerIteratorSynthetic)
	register_container_synthetic(abseil, AbseilHashContainerNodeSynthetic)

def make_array_from_pointer(valobj, size, raw_pointer_type=None):
	raw_pointer_type = raw_pointer_type or valobj.GetType()
	array_pointer_t = raw_pointer_type.GetPointeeType().GetArrayType(size).GetPointerType()

	return valobj.Cast(array_pointer_t).Dereference()

def remove_typedef(valobj, levels=1):
	target_type = valobj.GetType()

	for _ in range(0, levels):
		target_type = target_type.GetTypedefedType()

	return valobj.Cast(target_type)

def rename_valobj(valobj, name):
	return valobj.CreateValueFromAddress(name, valobj.GetLoadAddress(), valobj.GetType())

def try_extract_natural_index(valobj):
	# Drilldown into trivial types
	if valobj.GetType().GetNumberOfFields() == 1:
		valobj = valobj.GetChildAtIndex(0)

	# Try converting the valobj into a simple integral value
	basic = valobj.GetType().GetCanonicalType().GetBasicType()

	if basic in (lldb.eBasicTypeUnsignedInt, lldb.eBasicTypeUnsignedLong, lldb.eBasicTypeUnsignedLongLong):
		return valobj.GetValueAsUnsigned()

	if basic in (lldb.eBasicTypeInt, lldb.eBasicTypeLong, lldb.eBasicTypeLongLong):
		return valobj.GetValueAsSigned()

	return None

def is_pow2(number):
	return (number + 1) & number == 0

def is_prime(number):
	if number <= 1:
		return False

	for divisor in range(2, int(number**0.5)+1):
		if number % divisor == 0:
			return False

	return True

class SyntheticAdapter:
	def __init__(self, wrapped):
		self.wrapped = wrapped

	def __getattr__(self, name):
		return getattr(self.wrapped, name)

_scripted_t = None
_scripted_stack = []

class _ScriptedSynthetic(SyntheticAdapter):
	def __init__(self, valobj, dict):
		super().__init__(None)

		self.valobj = valobj

		global _scripted_t
		global _scripted_stack

		_scripted_stack.append(self)

def CreateScriptedValue(valobj, name, backend):
	global _scripted_t
	global _scripted_stack

	target = valobj.GetTarget()

	if _scripted_t is None:
		_scripted_t = valobj.EvaluateExpression('struct $lldb_toybox; ($lldb_toybox*) 0').GetType().GetPointeeType()

		target.GetDebugger().GetDefaultCategory().AddTypeSynthetic(
			lldb.SBTypeNameSpecifier(_scripted_t.GetName()),
			lldb.SBTypeSynthetic.CreateWithClassName(f'{__name__}._ScriptedSynthetic')
		)

	valobj = target.CreateValueFromData(name, lldb.SBData.CreateDataFromInt(0), _scripted_t)
	valobj.IsSynthetic()

	synthetic = _scripted_stack.pop()
	synthetic.wrapped = backend

	return valobj


class IterableContainer:
	"""Interface class describing required functionality for use with IterableContainerSyntheric"""

	def update(self):
		return

	def validate(self):
		return

	def get_size(self):
		return 0

	def get_summary(self):
		return f"size={self.get_size()}"

	def iterator(self):
		return None

class Value:
	"""Interface class describing required functionality for use with ValueContainerSynthetic"""

	def update(self):
		return

	def validate(self):
		return

	def get(self):
		return None

	def get_summary(self):
		return ""


class IterableContainerSynthetic:
	"""Implementation of the LLDB SyntheticChildrenProvider for IterableContainers"""

	def __init__(self, container, rename_children=True):
		self.container = container
		self.rename_children = rename_children

		self.update()

	def update(self):
		self.error = None
		self.size = None
		self.iterator = None
		self.cached_children = None

		# Let underlying container update if it is stateful
		self.container.update()

		# Offer ability to opt-out of calling the iterator if the container appears invalid
		self.error = self.container.validate()

	def has_children(self):
		return self.error is None

	def num_children(self):
		if self.error:
			return 0

		if not self.size:
			self.size = self.container.get_size()

		return self.size

	def get_child_at_index(self, index):
		if self.error:
			return None

		if index < 0:
			return None

		cached = 0

		if self.cached_children is not None:
			cached = len(self.cached_children)
		else:
			self.cached_children = list()
			self.iterator = self.container.iterator()

		if cached <= index and self.iterator is not None:
			try:
				child = next(self.iterator)

				if self.rename_children:
					child = rename_valobj(child, f"[{cached}]")

				self.cached_children.append(child)
				cached += 1
			except StopIteration:
				self.iterator = None

		if cached < index:
			return None

		return self.cached_children[index]

	def get_child_index(self, name):
		return None

	def get_summary(self):
		if self.error:
			return f"<Error: {self.error}>"

		return self.container.get_summary()

class ValueSynthetic:
	"""Implementation of the LLDB SyntheticChildrenProvider for Values"""

	def __init__(self, value, rename_to=None):
		self.value = value
		self.rename_to = rename_to

		self.update()

	def update(self):
		self.error = None

		self.content = None
		self.content_set = False

		# Let underlying value update if it is stateful
		self.value.update()

		# Offer ability to opt-out of inspecting the value if appears invalid
		self.error = self.value.validate()

	def populate(self):
		if self.content_set:
			return

		if not self.error:
			content = self.value.get()

			if content and self.rename_to:
				content = rename_valobj(content, self.rename_to)

			self.content = content

		self.content_set = True

	def has_children(self):
		return self.error is None

	def num_children(self):
		self.populate()

		return self.content and 1 or 0

	def get_child_at_index(self, index):
		self.populate()

		if index != 0:
			return None

		return self.content

	def get_child_index(self, name):
		return None

	def get_summary(self):
		if self.error:
			return f"<Error: {self.error}>"

		return self.value.get_summary()


class SortingSyntheticAdapter(SyntheticAdapter):
	def __init__(self, wrapped, is_map):
		super().__init__(wrapped)

		self.is_map = is_map

	def update(self):
		self.children = None

		self.wrapped.update()

	def populate(self):
		if self.children is not None:
			return

		child_list = list()
		child_map = dict()

		# Iterate over map hashtable via provided generator
		for iter_index in range(0, self.wrapped.num_children()):
			child = self.wrapped.get_child_at_index(iter_index)

			# Iteration based order is often not that useful during debugging, try
			#  to extract a more natural index to order by
			key = self.is_map and child.GetChildMemberWithName('first') or child

			natural_index = try_extract_natural_index(key)

			if natural_index is None:
				# Nothing better to go by, iteration index will have to suffice
				child_list.append(rename_valobj(child, f'[{iter_index}]'))
			else:
				# Since we are ordering by natural_index, it makes sense to give some
				#  additional prefix describing the typename of the ID
				prefix = key.GetType().GetUnqualifiedType().GetName()

				if self.is_map:
					# If the key has no synthetic its natural_index is likely a full
					#  representation, show only the mapped value to the user
					if not key.IsSynthetic():
						child = child.GetChildMemberWithName('second')

				# Store the child by it's natural index
				child_map[natural_index] = rename_valobj(child, f'{prefix}({natural_index})')

		# Flush delayed natural index based children
		for index, child in sorted(child_map.items()):
			child_list.append(child)

		self.children = child_list

	def get_child_at_index(self, index):
		self.populate()

		return self.children[index]

class PagingSyntheticAdapter(SyntheticAdapter):

	class Pager:
		def __init__(self, root, level, offset):
			self.root = root
			self.level = level
			self.offset = offset

		def has_children(self):
			return True

		def num_children(self):
			return self.root.pager_num_children(self.level, self.offset)

		def get_child_at_index(self, index):
			return self.root.pager_get_child_at_index(self.level, self.offset, index)

	def __init__(self, wrapped, valobj, limits = [100, 10]):
		super().__init__(wrapped)

		self.valobj = valobj
		self.limits = limits

		self.total = 0
		self.levels = 0

		self.update()

	def pager_capacity(self, depth):
		if depth < 0:
			return self.total

		capacity = 1

		for limit in self.limits[:self.levels - depth]:
			capacity *= limit

		return capacity

	def pager_num_children(self, depth, offset):
		contains = min(self.total - offset, self.pager_capacity(depth - 1))

		if self.levels == depth:
			return contains

		return math.ceil(contains / self.pager_capacity(depth))

	def pager_get_child_at_index(self, depth, offset, index):
		if self.levels <= depth:
			return self.wrapped.get_child_at_index(offset + index)

		capacity = self.pager_capacity(depth)

		first = offset + capacity * index
		last = min(self.total, first + capacity - 1)

		return CreateScriptedValue(self.valobj, f"#{first} .. #{last}", self.Pager(self, depth + 1, first))

	def update(self):
		self.wrapped.update()

		self.total = self.wrapped.num_children()

		# Determine how many levels of paginators we need to fit
		#  within the per-level child count tresholds
		remain = self.total
		levels = 0

		for limit in self.limits:
			if remain <= limit:
				break

			remain = math.ceil(remain / limit)
			levels += 1

		self.levels = levels

	def has_children(self):
		return True

	def num_children(self):
		return self.pager_num_children(0, 0)

	def get_child_at_index(self, index):
		return self.pager_get_child_at_index(0, 0, index)


class LibCXXHashContainer(IterableContainer):
	def __init__(self, valobj):
		self.valobj = valobj

		# This provider serves both unordered_set/map, as they are both backed by the same
		#  hash table implementation, determine which variant we are
		typename = self.valobj.GetType().GetCanonicalType().GetName()
		match = re.search(r"^std::[^:]+::unordered_(map|set)", typename)

		self.is_map = match.group(1) == 'map'

	def update(self):
		# https://github.com/apple/llvm-project/blob/next/libcxx/include/__hash_table
		#   __compressed_pair<__first_node, __node_allocator>     __p1_;
		#   __compressed_pair<size_type, hasher>                  __p2_;
		self.table = self.valobj.GetChildMemberWithName("__table_");

	def get_bucket_count(self):
		return self.table.GetChildMemberWithName('__bucket_list_') \
			.GetChildMemberWithName('__ptr_')                      \
			.GetChildAtIndex(1)                                    \
			.GetChildMemberWithName('__value_')                    \
			.GetChildMemberWithName('__data_')                     \
			.GetChildAtIndex(0)                                    \
			.GetChildMemberWithName('__value_')                    \
			.GetValueAsUnsigned()

	def validate(self):
		bucket_count = self.get_bucket_count()

		if bucket_count != 0 and not is_pow2(bucket_count) and not is_prime(bucket_count):
			return f"Bucket count {bucket_count} is neither pow2 nor prime"

	def get_size(self):
		return self.table.GetChildMemberWithName("__p2_").GetChildAtIndex(0).GetChildMemberWithName("__value_").GetValueAsUnsigned()

	def iterator(self):
		first_node = self.table.GetChildMemberWithName("__p1_").GetChildAtIndex(0).GetChildMemberWithName("__value_")
		node_type = first_node.GetType().GetTemplateArgumentType(0).GetPointeeType()

		next = first_node.GetChildMemberWithName("__next_")

		while next.GetValueAsUnsigned(0):
			node = next.Dereference().Cast(node_type)

			next = node.GetChildMemberWithName("__next_")
			value = node.GetChildMemberWithName("__value_")

			if self.is_map:
				yield value.GetChildMemberWithName("__cc_")
			else:
				# By default `value` is of std::__hash_node<K, void*>::__node_type, which is
				#  a little too verbose, reduce to K
				yield remove_typedef(value)

class LibCXXHashContainerIterator(Value):
	def __init__(self, valobj):
		self.valobj = valobj

		# This provider serves both unordered_set/map, as they are both backed by the same
		#  hash table implementation, determine which variant we are
		typename = self.valobj.GetType().GetName()
		match = re.search(r"^std::[^:]+::unordered_(map|set)", typename)

		self.is_map = match.group(1) == 'map'

		# Map iterators are hash iterators in disguise, rebind
		if self.is_map:
			self.valobj = valobj.GetChildMemberWithName('__i_')

		# Determine node pointer type stored by this handle
		self.node_ptr_t = self.valobj.GetType().GetTemplateArgumentType(0)

	def get(self):
		node_ptr = self.valobj.GetChildMemberWithName('__node_')

		if node_ptr.GetValueAsUnsigned(0) == 0:
			return None

		node = node_ptr.Cast(self.node_ptr_t).Dereference()

		if self.is_map:
			return remove_typedef(node.GetChildMemberWithName('__value_').GetChildMemberWithName('__cc_'))
		else:
			return remove_typedef(node.GetChildMemberWithName('__value_'))

class LibCXXHashContainerNode(Value):
	def __init__(self, valobj):
		self.valobj = valobj

		# Determine node pointer type stored by this handle
		self.node_ptr_t = self.valobj.GetType().GetTemplateArgumentType(0).GetPointerType()

		# This provider serves both unordered_set/map, as they are both backed by the same
		#  hash table implementation, determine which variant we are
		typename = self.valobj.GetType().GetCanonicalType().GetName()
		match = re.search("::__(set|map)_node_handle_specifics>$", typename)

		self.is_map = match.group(1) == 'map'

	def get(self):
		node_ptr = self.valobj.GetChildMemberWithName('__ptr_')

		if node_ptr.GetValueAsUnsigned(0) == 0:
			return None

		node = node_ptr.Cast(self.node_ptr_t).Dereference()

		if self.is_map:
			return remove_typedef(node.GetChildMemberWithName('__value_').GetChildMemberWithName('__cc_'))
		else:
			return remove_typedef(node.GetChildMemberWithName('__value_'))


class LibCXXHashContainerSynthetic(SyntheticAdapter):
	typename_regex = "^std::[^:]+::unordered_(map|set)<.+> >$"

	def __init__(self, valobj, dict):
		container = LibCXXHashContainer(valobj)

		synthetic = IterableContainerSynthetic(container, False)
		synthetic = SortingSyntheticAdapter(synthetic, container.is_map)

		super().__init__(synthetic)

class LibCXXHashContainerIteratorSynthetic(SyntheticAdapter):
	typename_regex = "^std::[^:]+::unordered_(set|map)<.+> >::(const_)?iterator$"

	def __init__(self, valobj, dict):
		super().__init__(ValueSynthetic(LibCXXHashContainerIterator(valobj), rename_to='pointee'))

class LibCXXHashContainerNodeSynthetic(SyntheticAdapter):
	typename_regex = "^std::[^:]+::unordered_(set|map)<.+> >::node_type$"

	def __init__(self, valobj, dict):
		super().__init__(ValueSynthetic(LibCXXHashContainerNode(valobj), rename_to='stored'))


class AbseilHashContainer(IterableContainer):
	def __init__(self, valobj):
		self.valobj = valobj

		# Many flat_hash_... types are implemented with inheritance from raw_hash_set, and
		#  only differ in policy template parameters. As such much of the code can be shared
		#  between them. Determine which type we represent
		typename = self.valobj.GetType().GetCanonicalType().GetName()
		match = re.search(r"absl::[^:]+::(flat|node)_hash_(map|set)", typename)

		self.is_flat = match.group(1) == 'flat'
		self.is_map = match.group(2) == 'map'

		# The underlying hashtable stores elements in "slots", whose type is difficult to obtain.. at the time of
		#  writing, SB API does not let us get the typedefs in the policy template argument that would make this
		#  much simpler/robust. (https://discourse.llvm.org/t/traversing-member-types-of-a-type/72452/12)
		self.slot_ptr_t = None

		# Drilldown to the root class, which will be raw_hash_set<>
		root = self.valobj.GetType()

		while root.GetNumberOfDirectBaseClasses() != 0:
			root = root.GetDirectBaseClassAtIndex(0).GetType()

		# Obtain `raw_hash_set<>::iterator` from `raw_hash_set<>::begin()`
		iterator = None

		for index in range(0, root.GetNumberOfMemberFunctions()):
			func = root.GetMemberFunctionAtIndex(index)

			if func.GetName() == 'begin':
				iterator = func.GetReturnType()
				break

		# Obtain `raw_hash_set<>::slot*` from `raw_hash_set<>::iterator::slot()`
		for index in range(0, iterator.GetNumberOfMemberFunctions()):
			func = iterator.GetMemberFunctionAtIndex(index)

			if func.GetName() == "slot":
				self.slot_ptr_t = func.GetReturnType()
				break

		# Grab common member variables from compressed tuple
		self.common = self.valobj.GetChildMemberWithName('settings_').GetChildAtIndex(0).GetChildAtIndex(0).GetChildMemberWithName('value')

	def update(self):
		pass

	def get_capacity(self):
		return self.common.GetChildMemberWithName('capacity_').GetValueAsUnsigned()

	def validate(self):
		capacity = self.get_capacity()

		if not is_prime(capacity):
			return f"Capacity {capacity} is nto pow2"

		size = self.get_size()

		if capacity < size:
			return f"Size {size} exceeds capacity {capacity}"

	def get_size(self):
		return self.common.GetChildMemberWithName('size_').GetValueAsUnsigned() >> 1

	def iterator(self):
		capacity = self.get_capacity()

		ctrl_arr = make_array_from_pointer(self.common.GetChildMemberWithName('control_'), capacity)
		slot_arr = make_array_from_pointer(self.common.GetChildMemberWithName('slots_'), capacity, self.slot_ptr_t)

		for index in range(0, capacity):
			ctrl = ctrl_arr.GetChildAtIndex(index).GetValueAsUnsigned()

			if ctrl & 0x80:
				continue

			slot = slot_arr.GetChildAtIndex(index)

			if self.is_flat:
				if self.is_map:
					yield slot.GetChildMemberWithName('value')
				else:
					yield slot
			else:
				yield slot.Dereference()

class AbseilHashContainerIteratorValue(Value):
	def __init__(self, valobj):
		self.valobj = valobj

		typename = self.valobj.GetType().GetCanonicalType().GetName()

		# This value adapts both to const and normal iterators, rebind to the
		#  inner value immediately in case we are a const iterator
		if typename.endswith('const_iterator'):
			self.valobj = valobj.GetChildMemberWithName('inner_')

		# Determining the container type is possible from the policy of the containing class
		match = re.search(r"::(Node|Flat)Hash(Map|Set)Policy<", typename)

		self.is_flat = match.group(1) == 'Flat'
		self.is_map = match.group(2) == 'Map'

	def get(self):
		if self.valobj.GetChildMemberWithName('ctrl_').GetValueAsUnsigned() == 0:
			return None

		slot = self.valobj.GetChildMemberWithName('slot_').Dereference()

		if self.is_flat:
			if self.is_map:
				return remove_typedef(slot.GetChildMemberWithName('value'), 1)
			else:
				return remove_typedef(slot, 3)
		else:
			return slot.Dereference()

class AbseilHashContainerNodeValue(Value):
	def __init__(self, valobj):
		self.valobj = valobj

		# The same investigative work is required to obtain the policy's `slot_type`
		self.slot_ptr_t = None

		node_handle_base = self.valobj.GetType().GetDirectBaseClassAtIndex(0).GetType()

		for index in range(0, node_handle_base.GetNumberOfMemberFunctions()):
			func = node_handle_base.GetMemberFunctionAtIndex(index)

			if func.GetName() == "slot":
				self.slot_ptr_t = func.GetReturnType()
				break

		# Determining the container type is possible from the policy of the containing class
		typename = node_handle_base.GetCanonicalType().GetName()
		match = re.search(r"::(Node|Flat)Hash(Map|Set)Policy<", typename)

		self.is_flat = match.group(1) == 'Flat'
		self.is_map = match.group(2) == 'Map'

	def get(self):
		allocator = self.valobj.GetChildMemberWithName('alloc_')
		allocator.SetPreferSyntheticValue(True)

		assert(allocator.IsSynthetic())

		if allocator.GetNumChildren() == 0:
			return None

		slot = self.valobj.GetChildMemberWithName('slot_space_').AddressOf().Cast(self.slot_ptr_t).Dereference()

		if self.is_flat:
			if self.is_map:
				return remove_typedef(slot.GetChildMemberWithName('value'), 1)
			else:
				return remove_typedef(slot, 3)
		else:
			return slot.Dereference()


class AbseilHashContainerSynthetic(SyntheticAdapter):
	typename_regex = "^absl::[^:]+::(flat|node)_hash_(set|map)<.+> >$"

	def __init__(self, valobj, dict):
		container = AbseilHashContainer(valobj)

		synthetic = IterableContainerSynthetic(container, False)
		synthetic = SortingSyntheticAdapter(synthetic, container.is_map)

		super().__init__(synthetic)

class AbseilHashContainerIteratorSynthetic(SyntheticAdapter):
	typename_regex = "^absl::[^:]+::container_internal::raw_hash_set<.+> >::(const_)?iterator$"

	def __init__(self, valobj, dict):
		super().__init__(ValueSynthetic(AbseilHashContainerIteratorValue(valobj), rename_to='pointee'))

class AbseilHashContainerNodeSynthetic(SyntheticAdapter):
	typename_regex = "^absl::[^:]+::container_internal::raw_hash_set<.+> >::node_type$"

	def __init__(self, valobj, dict):
		super().__init__(ValueSynthetic(AbseilHashContainerNodeValue(valobj), rename_to='stored'))
