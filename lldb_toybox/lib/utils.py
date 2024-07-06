
import lldb

def make_array_from_pointer(valobj, size, raw_pointer_type=None):
	raw_pointer_type = raw_pointer_type or valobj.GetType()
	array_pointer_t = raw_pointer_type.GetPointeeType().GetArrayType(size).GetPointerType()

	return valobj.Cast(array_pointer_t).Dereference()

def canonize_synthetic_valobj(valobj):
	"""
		Synthetics seem to receive all sorts of weird values despite the options
		 set on the registered SBTypeSynthetic object. This is possibly an Xcode
		 integration quirk, rather than a fault of the LLDB infra.

		This function can be used to strip away a bunch of unneeded wrappers from
		 the received valobj, including pointers, references, and unnecessary 
		 typedefs
	"""
	target_type = valobj.GetType()

	if target_type.IsPointerType() or target_type.IsReferenceType():
		valobj = valobj.Dereference().GetNonSyntheticValue()

	target_type = valobj.GetType().GetCanonicalType().GetUnqualifiedType()

	return valobj.Cast(target_type)

def remove_typedef(valobj, levels=1):
	target_type = valobj.GetType()

	for _ in range(0, levels):
		target_type = target_type.GetTypedefedType()

	return valobj.Cast(target_type)

def rename_valobj(valobj, name):
	return valobj.CreateValueFromAddress(name, valobj.GetLoadAddress(), valobj.GetType())

def is_pow2(number):
	return (number + 1) & number == 0

def is_prime(number):
	if number <= 1:
		return False

	for divisor in range(2, int(number**0.5)+1):
		if number % divisor == 0:
			return False

	return True

class Cache:
	"""Simple function decorator which caches the return value per process/stop"""

	def __init__(self, per=None):
		if not per or per not in ['process', 'stop']:
			raise RuntimException()

		self.per = per

		self.cache = dict()
		self.last = None

	def __call__(self, func):
		def wrapped(obj, *args, **kwargs):
			proc = obj

			if not isinstance(proc, lldb.SBProcess):
				proc = obj.GetProcess()

			if not isinstance(proc, lldb.SBProcess):
				raise RuntimException()

			uid = proc.GetUniqueID()

			# Evict stale data when accesing a different process
			if self.last != uid:
				self.last = uid

				for uid, entry in list(self.cache.items()):
					if entry[0].GetNumThreads() != 0:
						continue

					del self.cache[uid]

			# Enrich context based on operation mode
			context = 0

			if self.per == 'stop':
				context = proc.GetStopID()

			# Check cache for compatible entry
			entry = self.cache.get(uid)

			if entry and entry[1] == context:
				return entry[2]

			# Otherwise compute it
			self.cache[uid] = (proc, context, func(obj, *args, **kwargs))

			return self.cache[uid][2]

		return wrapped
