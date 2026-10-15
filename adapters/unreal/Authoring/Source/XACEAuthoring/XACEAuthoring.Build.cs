using UnrealBuildTool;
public class XACEAuthoring : ModuleRules
{
    public XACEAuthoring(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
        PublicDependencyModuleNames.AddRange(new [] { "Core", "CoreUObject", "Engine", "Json" });
        PrivateDependencyModuleNames.AddRange(new [] { "UnrealEd", "AssetRegistry", "AssetTools", "Kismet", "InputCore" });
        AddEngineThirdPartyPrivateStaticDependencies(Target, "OpenSSL");
    }
}
