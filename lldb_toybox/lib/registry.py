
import lldb

import argparse
import re
import shlex

_synthetics = list()
_initializers = list()

_main_parser = argparse.ArgumentParser(
	prog='toybox',
	description='''
		A swiss army knife toolset for anything LLDB related with the goal of
		making debugging fun and enjoyable process.

		Focuses mostly on working around/fixing idiosyncrasies of Xcode
	'''
)
_main_subparser = _main_parser.add_subparsers(required=True)

class Command:
	def __init__(self, name=None):
		self.name = name
		pass

	def __call__(self, clazz):
		subparser = _main_subparser.add_parser(self.name)
		subparser.set_defaults(impl=clazz(subparser))

def Synthetic(clazz):
	_synthetics.append(clazz)
	return clazz

def Initializer(func):
	_initializers.append(func)
	return func


def deploy(debugger):
	deploy_main_command(debugger)

	for clazz in _synthetics:
		category_name = f'lldb-toybox.{clazz.category}'
		category = debugger.GetCategory(category_name)

		if not category.IsValid():
			category = debugger.CreateCategory(category_name)
			category.AddLanguage(lldb.eLanguageTypeC_plus_plus)
			category.SetEnabled(True)

		deploy_synthetic(category, clazz)

	deploy_init_hook(debugger)


def deploy_main_command(debugger):
	import sys

	# Instantiate main command in this module
	def main_command(debugger, command, result, internal_dict):
		args = _main_parser.parse_args(shlex.split(command))
		impl = args.impl
		del args.impl

		impl and impl.run(args)

	sys.modules[__name__].main_command = main_command

	# Register it
	debugger.HandleCommand('command script add -o -f {}.main_command toybox'.format(__name__))


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


def deploy_init_hook(debugger):
	result = lldb.SBCommandReturnObject()
	debugger.GetCommandInterpreter().HandleCommand(f'target stop-hook add -P {__name__}.LateInitStopHook', result)

	if not result.Succeeded():
		print(f"lldb-toybox failed to install late-initialization stop hook: {result.GetError()}")

class LateInitStopHook:
	def __init__(self, target, extra_args, dict):
		pass

	def disable(self, debugger):
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
		print("lldb-toybox is performing late-initialization, hold tight...")
		debugger = exe_ctx.GetTarget().GetDebugger()

		# Ensure we won't run again for this target
		self.disable(debugger)

		# Run initialization routines
		for func in _initializers:
			func(debugger, exe_ctx.GetTarget())
