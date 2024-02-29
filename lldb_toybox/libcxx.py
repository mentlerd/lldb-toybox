
from lldb_toybox.lib.adapter import SyntheticAdapter
from lldb_toybox.lib.iterable import IterableContainer, IterableContainerSynthetic
from lldb_toybox.lib.registry import Synthetic
from lldb_toybox.lib.sorting import SortingSyntheticAdapter
from lldb_toybox.lib.utils import *
from lldb_toybox.lib.value import Value, ValueSynthetic

import lldb

import re

class LibCXXHashContainer(IterableContainer):
	def __init__(self, valobj):
		self.valobj = canonize_synthetic_valobj(valobj)

		# This provider serves both unordered_set/map, as they are both backed by the same
		#  hash table implementation, determine which variant we are
		typename = self.valobj.GetType().GetCanonicalType().GetUnqualifiedType().GetName()
		match = re.search(r"^std::[^:]+::unordered_(?:multi)?(map|set)", typename)

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
		self.valobj = canonize_synthetic_valobj(valobj)

		# This provider serves both unordered_set/map, as they are both backed by the same
		#  hash table implementation, determine which variant we are
		self.is_map = re.search(r"std::[^:]+::__hash_const_iterator<", self.valobj.GetType().GetName()) is None

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
		self.valobj = canonize_synthetic_valobj(valobj)

		# Determine node pointer type stored by this handle
		self.node_ptr_t = self.valobj.GetType().GetTemplateArgumentType(0).GetPointerType()

		# This provider serves both unordered_set/map, as they are both backed by the same
		#  hash table implementation, determine which variant we are
		typename = self.valobj.GetType().GetCanonicalType().GetUnqualifiedType().GetName()
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

@Synthetic
class LibCXXHashContainerSynthetic(SyntheticAdapter):
	category = "libcxx-overrides"
	recognizers = [
		lldb.SBTypeNameSpecifier("^std::[^:]+::unordered_(multi)?(map|set)<.+> >$", True),
	]

	def __init__(self, valobj, dict):
		container = LibCXXHashContainer(valobj)

		synthetic = IterableContainerSynthetic(container, False)
		synthetic = SortingSyntheticAdapter(synthetic, container.is_map)

		super().__init__(synthetic)

@Synthetic
class LibCXXHashContainerIteratorSynthetic(SyntheticAdapter):
	category = "libcxx-overrides"
	recognizers = [
		lldb.SBTypeNameSpecifier("^std::[^:]+::unordered_(multi)?(set|map)<.+> >::(const_)?iterator$", True),
		lldb.SBTypeNameSpecifier("^std::[^:]+::(__hash_map_iterator<std::[^:]+::__hash_iterator|__hash_const_iterator)<std::[^:]+::__hash_node<", True),		
	]

	def __init__(self, valobj, dict):
		super().__init__(ValueSynthetic(LibCXXHashContainerIterator(valobj), rename_to='pointee'))

@Synthetic
class LibCXXHashContainerNodeSynthetic(SyntheticAdapter):
	category = "libcxx"
	recognizers = [
		lldb.SBTypeNameSpecifier("^std::[^:]+::unordered_(multi)?(set|map)<.+> >::node_type$", True),
		lldb.SBTypeNameSpecifier("^std::[^:]+::__basic_node_handle<std::[^:]+::__hash_node<", True),		
	]

	def __init__(self, valobj, dict):
		super().__init__(ValueSynthetic(LibCXXHashContainerNode(valobj), rename_to='stored'))
