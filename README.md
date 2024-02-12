# lldb-toybox 🧰
Various LLDB extensions that make debugging C++ code a bit more seamless:

## Features

### Naturally ordered hash table contents
The native [LLDB data formatters](https://lldb.llvm.org/use/variable.html) enumerate hash table based containers in iteration order. This can
be inconvenient for large registries where a simple integral key is mapped to a more complex type: finding the appropriate entry is difficult,
as the elements are listed in _iteration order_ by default.

Type formatter implementations in `lldb-toybox` print elements in their _natural order_ if the key of an entry is convertible to an integral type:

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

### Extended `node_type` support
Native LLDB formatters lack support for various `node_type`s for containers. `lldb-toybox` adds it's own implementation:
```
(std::unordered_map<int, int>::node_type) <Empty node>

(std::unordered_map<int, int>::node_type) {
  stored = (first = 100, second = 1000)
}
```

### Extended `iterator` support
Native LLDB formatters iterator support is extended to provide better summaries.
```
(absl::container_internal::raw_hash_set<...>::iterator) <End iterator>

(absl::container_internal::raw_hash_set<...>::iterator) {
  pointee = (first = 200, second = 2000)
}
```

## Supported types

### libc++ [`std::unordered_(set|map)`](https://en.cppreference.com/w/cpp/container)
Implemented by `hash_container_support.py`, enabled by the `lldb-toybox.libcxx` and `lldb-toybox.libcxx-overrides` type categories.

* Support for naturally ordered elements (overrides [native implementation](https://github.com/apple/llvm-project/blob/next/lldb/source/Plugins/Language/CPlusPlus/LibCxxUnorderedMap.cpp)!)
* Support for `node_type`

> [!WARNING]
> Replacing the native data formatter implementation of LLDB for libc++ types with a Python script comes with a slight
> performance impact, and has a risk of breaking for future libc++ versions.
>
> If you are experiencing issues you can disable the override through the `lldb-toybox.libcxx-overrides` type category:  
> `type category disable lldb-toybox.libcxx-overrides`

### Abseil [`absl::(node|flat)_hash_(set|map)`](https://abseil.io/docs/cpp/guides/container#hash-tables)
Implemented by `hash_container_support.py`, enabled by the `lldb-toybox.abseil` type category.

* Support for naturally ordered elements
* Support for `iterator` and `const_iterator`
* Support for `node_type`
