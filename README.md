# lldb-toybox
Various LLDB extensions that make debugging C++ code a bit more seamless

## Ordered hash table containers
Implemented by `hash_container_support.py`

The native [LLDB data formatters](https://lldb.llvm.org/use/variable.html) enumerate hash table based containers in iteration order. This can
be inconvenient for large registries where a simple integral key is mapped to a more complex type: finding the appropriate entry is difficult,
as the elements are listed in _iteration order_ by default.

`lldb-toybox` provides an custom [synthetic children provider](https://lldb.llvm.org/use/variable.html#synthetic-children) for supported container
types where the key can be converted into a simple integral value (IE by extracting the only field from the value), and prints elements in their
_natural order_ instead:

<table>
<tr>
<th>Native LLDB</th>
<th>lldb-toybox</th>
</tr>
<tr>
<td>

```
(std::unordered_map<int, int>) size=8 {
  [0] = (first = 7, second = 7)
  [1] = (first = 6, second = 6)
  [2] = (first = 5, second = 5)
  [3] = (first = 4, second = 4)
  [4] = (first = 3, second = 3)
  [5] = (first = 2, second = 2)
  [6] = (first = 1, second = 1)
  [7] = (first = 0, second = 0)
}

(std::unordered_set<int>) size=8 {
  [0] = 7
  [1] = 6
  [2] = 5
  [3] = 4
  [4] = 3
  [5] = 2
  [6] = 1
  [7] = 0
}
```

</td>
<td>

```
(std::unordered_map<int, int>) size=8 {
  int(0) = 0
  int(1) = 1
  int(2) = 2
  int(3) = 3
  int(4) = 4
  int(5) = 5
  int(6) = 6
  int(7) = 7
}

(std::unordered_set<int>) size=8 {
  int(0) = 0
  int(1) = 1
  int(2) = 2
  int(3) = 3
  int(4) = 4
  int(5) = 5
  int(6) = 6
  int(7) = 7
}
```

</td>
</tr>
</table>

In addition to providing an override for libc++ types, the script also supports [Abseil's hash table](https://abseil.io/docs/cpp/guides/container#hash-tables)
based containers.

> [!WARNING]
> Replacing the [native data formatter implementation](https://github.com/apple/llvm-project/blob/next/lldb/source/Plugins/Language/CPlusPlus/LibCxxUnorderedMap.cpp)
> of LLDB for libc++ types with a Python script comes with a performance impact, and has a risk of breaking for future libc++ versions.
>
> If you are experiencing issues you can disable the override through the `lldb-toybox.libcxx-overrides` type category:  
> `type category disable lldb-toybox.libcxx-overrides`
