
from lldb_toybox.lib.adapter import SyntheticAdapter

import lldb

_scripted_t = None
_scripted_stack = []

class ScriptedSynthetic(SyntheticAdapter):
	def __init__(self, valobj, dict):
		super().__init__(None)

		self.valobj = valobj

		global _scripted_t
		global _scripted_stack

		_scripted_stack.append(self)

def create_scripted_value(valobj, name, backend):
	global _scripted_t
	global _scripted_stack

	target = valobj.GetTarget()

	if _scripted_t is None:
		_scripted_t = valobj.EvaluateExpression('struct $lldb_toybox; ($lldb_toybox*) 0').GetType().GetPointeeType()

		target.GetDebugger().GetDefaultCategory().AddTypeSynthetic(
			lldb.SBTypeNameSpecifier(_scripted_t.GetName()),
			lldb.SBTypeSynthetic.CreateWithClassName(f'{__name__}.ScriptedSynthetic')
		)

	valobj = target.CreateValueFromData(name, lldb.SBData.CreateDataFromInt(0), _scripted_t)
	valobj.IsSynthetic()

	synthetic = _scripted_stack.pop()
	synthetic.wrapped = backend

	return valobj
