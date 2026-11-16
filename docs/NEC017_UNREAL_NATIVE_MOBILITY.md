# Unreal existing-object projection mobility contract

Native projection writes authoritative world transforms to every bound actor. The currently supported profile requires a Movable root component on every bound actor. Static or Stationary native roots are refused by BindNativeActors before binding/authority startup; the adapter must not silently change their mobility. Unbound decorative native objects retain their ownership/profile.

Changing mobility is an explicit creator-side native authoring decision in a new reviewed revision. It may affect lighting/performance and is not an automatic import conversion. The NEC017 imported test copy records that decision, preserves original native source, and saves/reapproves the copied map. Its first test must prove that the original Static-root configuration refuses and leaves native transforms/resources unchanged, followed by successful Movable-profile admission, real Play and exact applied projections.

The failed 20261116/unreal-existing-play-a proof exposed this omission: identity/resource checks passed while native input movement and projection failed and Unreal reported Static mobility warnings. Preserve the failed proof. Closure requires native refusal/success verification and current-source evidence; compile success alone does not close it.

## Physical installed-resource integrity

Cooked Unreal PakFile intentionally excludes loose uasset/umap/ubulk/uexp resources from its virtual reader (installed UE5.7 source IPlatformFilePak.cpp, ExcludedNonPakExtensions). Native package catalogs archive exact creator resource bytes separately from cooked presentation. FXaceNativeHostClient::FileHash must hash physical installed files through GetPlatformPhysical rather than the virtual asset reader; it must not resolve packaged aliases, alter platform file chains, bypass checksum comparison or load these source resources as gameplay.

The streaming hash retains bounded memory, refuses failed/short reads and size changes, and returns the ordinary SHA256 identity. Original source and cooked artifact checks use the same physical-file contract. Verify current native Play, successful cooked gameplay and unchanged-package tamper refusal. Failed packaged c launch is retained; its source resource was present and byte-identical to the manifest, but the virtual file reader refused its extension.
