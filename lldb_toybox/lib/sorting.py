
from lldb_toybox.lib.adapter import SyntheticAdapter
from lldb_toybox.lib.utils import *

import lldb

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
				child_map[(natural_index, child.GetLoadAddress())] = rename_valobj(child, f'{prefix}({natural_index})')

		# Flush delayed natural index based children
		for (index, addr), child in sorted(child_map.items()):
			child_list.append(child)

		self.children = child_list

	def get_child_at_index(self, index):
		self.populate()

		return self.children[index]
