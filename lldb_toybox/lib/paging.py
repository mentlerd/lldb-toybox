
from lldb_toybox.lib.adapter import SyntheticAdapter
from lldb_toybox.lib.scripted import create_scripted_value

import lldb

import math

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

		return create_scripted_value(self.valobj, f"#{first} .. #{last}", self.Pager(self, depth + 1, first))

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
