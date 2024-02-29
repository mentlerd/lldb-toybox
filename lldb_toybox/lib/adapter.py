
class SyntheticAdapter:
	def __init__(self, wrapped):
		self.wrapped = wrapped

	def __getattr__(self, name):
		return getattr(self.wrapped, name)
