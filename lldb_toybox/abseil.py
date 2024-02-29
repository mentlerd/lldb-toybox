
from lldb_toybox.lib.adapter import SyntheticAdapter
from lldb_toybox.lib.iterable import IterableContainer, IterableContainerSynthetic
from lldb_toybox.lib.registry import Synthetic
from lldb_toybox.lib.sorting import SortingSyntheticAdapter
from lldb_toybox.lib.utils import *
from lldb_toybox.lib.value import Value, ValueSynthetic

import lldb

import re

class AbseilHashContainer(IterableContainer):
	def __init__(self, valobj):
		self.valobj = canonize_synthetic_valobj(valobj)

		# Many flat_hash_... types are implemented with inheritance from raw_hash_set, and
		#  only differ in policy template parameters. As such much of the code can be shared
		#  between them. Determine which type we represent
		typename = self.valobj.GetType().GetCanonicalType().GetUnqualifiedType().GetName()
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

		if not is_pow2(capacity):
			return f"Capacity {capacity} is not pow2"

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
		self.valobj = canonize_synthetic_valobj(valobj)

		typename = self.valobj.GetType().GetCanonicalType().GetUnqualifiedType().GetName()

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
		self.valobj = canonize_synthetic_valobj(valobj)

		# The same investigative work is required to obtain the policy's `slot_type`
		self.slot_ptr_t = None

		node_handle_base = self.valobj.GetType().GetDirectBaseClassAtIndex(0).GetType()

		for index in range(0, node_handle_base.GetNumberOfMemberFunctions()):
			func = node_handle_base.GetMemberFunctionAtIndex(index)

			if func.GetName() == "slot":
				self.slot_ptr_t = func.GetReturnType()
				break

		# Determining the container type is possible from the policy of the containing class
		typename = node_handle_base.GetCanonicalType().GetUnqualifiedType().GetName()
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

@Synthetic
class AbseilHashContainerSynthetic(SyntheticAdapter):
	category = "abseil"
	recognizers = [
		lldb.SBTypeNameSpecifier("^absl::[^:]+::(flat|node)_hash_(set|map)<.+> >$", True),
	]

	def __init__(self, valobj, dict):
		container = AbseilHashContainer(valobj)

		synthetic = IterableContainerSynthetic(container, False)
		synthetic = SortingSyntheticAdapter(synthetic, container.is_map)

		super().__init__(synthetic)

@Synthetic
class AbseilHashContainerIteratorSynthetic(SyntheticAdapter):
	category = "abseil"
	recognizers = [
		lldb.SBTypeNameSpecifier("^absl::[^:]+::container_internal::raw_hash_set<.+> >::(const_)?iterator$", True)
	]

	def __init__(self, valobj, dict):
		super().__init__(ValueSynthetic(AbseilHashContainerIteratorValue(valobj), rename_to='pointee'))

@Synthetic
class AbseilHashContainerNodeSynthetic(SyntheticAdapter):
	category = "abseil"
	recognizers = [
		lldb.SBTypeNameSpecifier("^absl::[^:]+::container_internal::raw_hash_set<.+> >::node_type$", True),
		lldb.SBTypeNameSpecifier("^absl::[^:]+::container_internal::node_handle<absl::[^:]+::container_internal::(Flat|Node)Hash(Map|Set)Policy", True),
	]

	def __init__(self, valobj, dict):
		super().__init__(ValueSynthetic(AbseilHashContainerNodeValue(valobj), rename_to='stored'))
