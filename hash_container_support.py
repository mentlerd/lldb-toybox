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
	register_container_synthetic(libcxx_overrides, LibCXXHashContainerSyntheticProvider)

	libcxx = register_category(debugger, "lldb-toybox.libcxx")
	abseil = register_category(debugger, "lldb-toybox.abseil")

	register_container_synthetic(libcxx, LibCXXHashContainerNodeSyntheticProvider)

	register_container_synthetic(abseil, AbseilHashContainerSyntheticProvider)
	register_container_synthetic(abseil, AbseilHashContainerIteratorSyntheticProvider)
	register_container_synthetic(abseil, AbseilHashContainerConstIteratorSyntheticProvider)
	register_container_synthetic(abseil, AbseilHashContainerNodeSyntheticProvider)

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

def build_ordered_child_list(generator, is_map):
	child_list = list()
	child_map = dict()

	# Iterate over map hashtable via provided generator
	for iter_index, valobj in enumerate(generator()):
		child = valobj

		# Iteration based order is often not that useful during debugging, try
		#  to extract a more natural index to order by
		key = is_map and valobj.GetChildMemberWithName('first') or valobj

		natural_index = try_extract_natural_index(key)

		if natural_index is None:
			# Nothing better to go by, iteration index will have to suffice
			child_list.append(rename_valobj(child, f'[{iter_index}]'))
		else:
			# Since we are ordering by natural_index, it makes sense to give some
			#  additional prefix describing the typename of the ID
			prefix = key.GetType().GetUnqualifiedType().GetName()

			if is_map:
				# If the key has no synthetic its natural_index is likely a full
				#  representation, show only the mapped value to the user
				if not key.IsSynthetic():
					child = valobj.GetChildMemberWithName('second')

			# Store the child by it's natural index
			child_map[natural_index] = rename_valobj(child, f'{prefix}({natural_index})')

	# Flush delayed natural index based children
	for index, child in sorted(child_map.items()):
		child_list.append(child)

	return child_list

class LibCXXHashContainerSyntheticProvider:
	typename_regex = "^std::[^:]+::unordered_(set|map)<.+> >$"

	def __init__(self, valobj, dict):
		self.valobj = valobj

		# This provider serves both unordered_set/map, as they are both backed by the same
		#  hash table implementation, determine which variant we are
		typename = self.valobj.GetType().GetCanonicalType().GetName()
		match = re.search(r"^std::[^:]+::unordered_(map|set)", typename)

		self.is_map = match.group(1) == 'map'

		self.update()

	def update(self):
		# https://github.com/apple/llvm-project/blob/next/libcxx/include/__hash_table
		#   __compressed_pair<__first_node, __node_allocator>     __p1_;
		#   __compressed_pair<size_type, hasher>                  __p2_;
		size_and_hasher = self.valobj.GetChildMemberWithName("__table_").GetChildMemberWithName("__p2_")

		# Eagerly grab size to provide summaries
		self.size = size_and_hasher.GetChildAtIndex(0).GetChildMemberWithName("__value_").GetValueAsUnsigned(0)

		# Container elements are discovered lazily
		self.child_list = None

	def populate(self):
		if self.child_list:
			return

		hash_table = self.valobj.GetChildMemberWithName("__table_")

		first_node = hash_table.GetChildMemberWithName("__p1_").GetChildAtIndex(0).GetChildMemberWithName("__value_")
		node_type = first_node.GetType().GetTemplateArgumentType(0).GetPointeeType()

		def generator():
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

		self.child_list = build_ordered_child_list(generator, self.is_map)

	def has_children(self):
		return True # This formatter _may have_ children

	def num_children(self):
		return self.size

	def get_child_at_index(self, index):
		self.populate()

		return self.child_list[index]

	def get_child_index(self, name):
		return None

	def get_summary(self):
		return f"size={self.size}"

class LibCXXHashContainerNodeSyntheticProvider:
	typename_regex = "^std::[^:]+::unordered_(set|map)<.+> >::node_type$"

	def __init__(self, valobj, dict):
		self.valobj = valobj

		# Determine node pointer type stored by this handle
		self.node_ptr_t = self.valobj.GetType().GetTemplateArgumentType(0).GetPointerType()

		# This provider serves both unordered_set/map, as they are both backed by the same
		#  hash table implementation, determine which variant we are
		typename = self.valobj.GetType().GetCanonicalType().GetName()
		match = re.search("::__(set|map)_node_handle_specifics>$", typename)

		self.is_map = match.group(1) == 'map'

		self.update()

	def update(self):
		node_ptr = self.valobj.GetChildMemberWithName('__ptr_')

		self.is_empty = node_ptr.GetValueAsUnsigned() == 0
		self.stored = None

		if self.is_empty:
			return

		node = node_ptr.Cast(self.node_ptr_t).Dereference()
		stored = None

		if self.is_map:
			stored = remove_typedef(node.GetChildMemberWithName('__value_').GetChildMemberWithName('__cc_'))
		else:
			stored = remove_typedef(node.GetChildMemberWithName('__value_'))

		self.stored = rename_valobj(stored, 'stored')

	def has_children(self):
		return not self.is_empty

	def num_children(self):
		if not self.stored:
			return 0

		return 1

	def get_child_at_index(self, index):
		if not self.stored:
			return

		if not index == 0:
			return

		return self.stored

	def get_child_index(self, name):
		return None

	def get_summary(self):
		return self.is_empty and "<Empty node>" or ""

class AbseilHashContainerSyntheticProvider:
	typename_regex = "^absl::[^:]+::(flat|node)_hash_(set|map)<.+> >$"

	def __init__(self, valobj, dict):
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

		self.update()

	def update(self):
		# Grab common member variables from compressed tuple
		self.common = self.valobj.GetChildMemberWithName('settings_').GetChildAtIndex(0).GetChildAtIndex(0).GetChildMemberWithName('value')

		# Grab size of map, note that 'size_' contains an unrelated flag on the least significant bit
		self.size = self.common.GetChildMemberWithName('size_').GetValueAsUnsigned() >> 1

		# Grab capacity of map, this will help with accessing the ctrl/slot arrays
		self.capacity = self.common.GetChildMemberWithName('capacity_').GetValueAsUnsigned()

		# Container elements are discovered lazily
		self.child_list = None

	def populate(self):
		if self.child_list:
			return

		ctrl_arr = make_array_from_pointer(self.common.GetChildMemberWithName('control_'), self.capacity)
		slot_arr = make_array_from_pointer(self.common.GetChildMemberWithName('slots_'), self.capacity, self.slot_ptr_t)

		def generator():
			for index in range(0, self.capacity):
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

		self.child_list = build_ordered_child_list(generator, self.is_map)

	def has_children(self):
		return True # This formatter _may have_ children

	def num_children(self):
		return self.size

	def get_child_at_index(self, index):
		self.populate()

		return self.child_list[index]

	def get_child_index(self, name):
		return None

	def get_summary(self):
		return f"size={self.size}"

class AbseilHashContainerIteratorSyntheticProvider:
	typename_regex = "^absl::[^:]+::container_internal::raw_hash_set<.+> >::iterator$"

	def __init__(self, valobj, dict):
		self.valobj = valobj

		# Determining the container type is possible from the policy of the containing class
		typename = self.valobj.GetType().GetCanonicalType().GetName()
		match = re.search(r"::(Node|Flat)Hash(Map|Set)Policy<", typename)

		self.is_flat = match.group(1) == 'Flat'
		self.is_map = match.group(2) == 'Map'

		self.update()

	def update(self):
		self.is_end = self.valobj.GetChildMemberWithName('ctrl_').GetValueAsUnsigned() == 0
		self.pointee = None

		if self.is_end:
			return

		slot = self.valobj.GetChildMemberWithName('slot_').Dereference()
		pointee = None

		if self.is_flat:
			if self.is_map:
				pointee = remove_typedef(slot.GetChildMemberWithName('value'), 1)
			else:
				pointee = remove_typedef(slot, 3)
		else:
			pointee = slot.Dereference()

		self.pointee = rename_valobj(pointee, 'pointee')

	def has_children(self):
		return not self.is_end

	def num_children(self):
		if not self.pointee:
			return 0

		return 1

	def get_child_at_index(self, index):
		if not self.pointee:
			return

		if index != 0:
			return

		return self.pointee

	def get_child_index(self, name):
		return None

	def get_summary(self):
		return self.is_end and "<End iterator>" or ""

class AbseilHashContainerConstIteratorSyntheticProvider:
	typename_regex = "^absl::[^:]+::container_internal::raw_hash_set<.+> >::const_iterator$"

	def __init__(self, valobj, dict):
		self.valobj = valobj
		self.update()

	def update(self):
		self.inner = self.valobj.GetChildMemberWithName('inner_')
		self.inner.SetPreferSyntheticValue(True)

	def has_children(self):
		return self.inner.MightHaveChildren()

	def num_children(self):
		return self.inner.GetNumChildren()

	def get_child_at_index(self, index):
		return self.inner.GetChildAtIndex(index)

	def get_child_index(self, name):
		return None

	def get_summary(self):
		return self.inner.GetSummary() or ''

class AbseilHashContainerNodeSyntheticProvider:
	typename_regex = "^absl::[^:]+::container_internal::raw_hash_set<.+> >::node_type$"

	def __init__(self, valobj, dict):
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

		self.update()

	def update(self):
		allocator = self.valobj.GetChildMemberWithName('alloc_')
		allocator.SetPreferSyntheticValue(True)

		assert(allocator.IsSynthetic())

		self.is_empty = allocator.GetNumChildren() == 0
		self.stored = None

		if self.is_empty:
			return

		slot = self.valobj.GetChildMemberWithName('slot_space_').AddressOf().Cast(self.slot_ptr_t).Dereference()
		stored = None

		if self.is_flat:
			if self.is_map:
				stored = remove_typedef(slot.GetChildMemberWithName('value'), 1)
			else:
				stored = remove_typedef(slot, 3)
		else:
			stored = slot.Dereference()

		self.stored = rename_valobj(stored, 'stored')

	def has_children(self):
		return not self.is_empty

	def num_children(self):
		if not self.stored:
			return 0

		return 1

	def get_child_at_index(self, index):
		if not self.stored:
			return

		if not index == 0:
			return

		return self.stored

	def get_child_index(self, name):
		return None

	def get_summary(self):
		return self.is_empty and "<Empty node>" or ""
