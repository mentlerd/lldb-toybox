
from lldb_toybox.lib.utils import *

import lldb

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
