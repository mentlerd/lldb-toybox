
import lldb

_synthetics = list()

def Synthetic(clazz):
	_synthetics.append(clazz)
	return clazz

def deploy_synthetic(category, clazz):
	class_name = f"{clazz.__module__}.{clazz.__qualname__}"
	print(f"{class_name}")

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
	for clazz in _synthetics:
		category_name = f'lldb-toybox.{clazz.category}'
		category = debugger.GetCategory(category_name)

		if not category.IsValid():
			category = debugger.CreateCategory(category_name)
			category.AddLanguage(lldb.eLanguageTypeC_plus_plus)
			category.SetEnabled(True)

		deploy_synthetic(category, clazz)
