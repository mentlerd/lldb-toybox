
from lldb_toybox.lib.utils import *

import lldb

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
