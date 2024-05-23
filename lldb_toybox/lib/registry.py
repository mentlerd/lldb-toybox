
import lldb

import re

_synthetics = list()

def Synthetic(clazz):
	_synthetics.append(clazz)
	return clazz

def deploy_synthetic(category, clazz):
	class_name = f"{clazz.__module__}.{clazz.__qualname__}"

	for synth in category.get_synthetics_array():
		if class_name in str(synth):
			return

	options = lldb.eTypeOptionNone
	options |= lldb.eTypeOptionCascade
	options |= lldb.eTypeOptionFrontEndWantsDereference

	synthetic = lldb.SBTypeSynthetic.CreateWithClassName(class_name)
	synthetic.SetOptions(options)

	summary = lldb.SBTypeSummary.CreateWithScriptCode(f'''
		return {class_name}(valobj.GetNonSyntheticValue(), internal_dict).get_summary()
	''')
	summary.SetOptions(options)

	for recognizer in clazz.recognizers:
		category.AddTypeSynthetic(recognizer, synthetic)
		category.AddTypeSummary(recognizer, summary)

def deploy(debugger):

	# Register synthetics we know about
	for clazz in _synthetics:
		category_name = f'lldb-toybox.{clazz.category}'
		category = debugger.GetCategory(category_name)

		if not category.IsValid():
			category = debugger.CreateCategory(category_name)
			category.AddLanguage(lldb.eLanguageTypeC_plus_plus)
			category.SetEnabled(True)

		deploy_synthetic(category, clazz)

	# Register a stop hook for deferred initialization of things that depend on the target
	result = lldb.SBCommandReturnObject()
	debugger.GetCommandInterpreter().HandleCommand(f'target stop-hook add -P {__name__}.LateInitStopHook', result)

	if not result.Succeeded():
		print(f"lldb-toybox failed to install late-initialization stop hook: {result.GetError()}")

class LateInitStopHook:
	def __init__(self, target, extra_args, dict):
		pass

	def disable(self, exe_ctx):
		debugger = exe_ctx.GetTarget().GetDebugger()

		result = lldb.SBCommandReturnObject()
		interpreter = debugger.GetCommandInterpreter()
		interpreter.HandleCommand('target stop-hook list', result)

		if not result.Succeeded():
			raise RuntimException()

		match = re.match(f'Hook: (\\d).*?Class:{__name__}.LateInitStopHook', result.GetOutput(), re.DOTALL)

		if not match:
			raise RuntimException()

		debugger.HandleCommand(f'target stop-hook disable {match.group(1)}')

	def handle_stop(self, exe_ctx, stream):
		print("lldb-toybox is performing late-initialization, hold tight...", end=" ")

		# First time initialization should be done once
		self.disable(exe_ctx)

		# Scan target for interesting types we might have synthetics for
		
		
