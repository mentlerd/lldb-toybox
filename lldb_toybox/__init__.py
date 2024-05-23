#
# Usage:
# > (lldb) command script import <path-to-this-file>
#

import lldb

def __lldb_init_module(debugger, dict):
	import lldb_toybox.lib.registry

	import lldb_toybox.libcxx
	import lldb_toybox.abseil

	lldb_toybox.lib.registry.deploy(debugger)
