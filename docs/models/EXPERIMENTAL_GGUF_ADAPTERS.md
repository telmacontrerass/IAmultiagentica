# Experimental GGUF adapters

GGUF adapters are declarations outside the stable imported-model registry. They
bind an exact architecture, embedded-template SHA-256, runtime, safe template
transformation, textual tool-call encoding, and reinjection contract. A family
name alone can never activate an adapter.

The catalog is `ci2lab/catalog/experimental_gguf_adapters.json`. Its `enabled`
field permits an adapter to participate in explicit experimental validation;
setting it to `false` disables matching. This does not change any model profile.

```powershell
ci2lab models adapters list
ci2lab models adapters inspect experimental_glm_global_tools_v1
ci2lab models adapters suite --name adapted-tools
```

## Pipeline

1. Inspect the GGUF and calculate the literal template hash.
2. Select by adapter ID plus architecture, hash, and runtime.
3. Apply an allow-listed transform with preconditions and hash postconditions.
4. Render tools with the runtime and pass deterministic prompt gates.
5. Normalize raw text using the manifest and validate arguments against schema.
6. Execute only calls with `confidence=exact`.
7. Discard premature trailing prose from user-visible/history semantics while
   preserving it in evidence.
8. Reinject using the declared historical protocol and validate finalization.

Only `inject_global_tools_as_message` is supported. Arbitrary code, dynamic
template generation, and family-specific selection are not supported.

`adapted_native` is intentionally local to this subsystem. It means that a model
uses its historical protocol, the runtime may expose it as text, and CI2Lab
normalizes it through an exact, validated manifest. It is not part of the stable
global `ToolMode`, and stable profiles cannot select it.

The adapted-tools scenario catalog separates deterministic unit/simulated cases
from live cases. The existing live GLM `add` run passed in two rounds; other live
scenarios remain opt-in because each requires loading and running the 9.4B model.
No result is inferred for a scenario that was not run.
