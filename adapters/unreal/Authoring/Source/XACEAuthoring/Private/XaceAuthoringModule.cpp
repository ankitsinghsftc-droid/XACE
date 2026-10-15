#include "Modules/ModuleManager.h"
#include "HAL/IConsoleManager.h"
#include "XaceAuthoringProofCommandlet.h"
#include "HAL/PlatformMisc.h"
class FXaceAuthoringModule:public IModuleInterface
{
    IConsoleObject* Proof=nullptr;
public:
    void StartupModule() override
    {
        // Explicit fixture command only; no import, runtime or project-open hooks.
        Proof=IConsoleManager::Get().RegisterConsoleCommand(TEXT("XACE.Authoring.Proof"),TEXT("Run the isolated NEC-006 editor fixture proof"),FConsoleCommandWithArgsDelegate::CreateLambda([](const TArray<FString>& Args){if(Args.Num()==1 && Args[0]==TEXT("interactive")){int32 Result=UXaceAuthoringProofCommandlet::Run(Args[0]);FPlatformMisc::RequestExitWithStatus(false,uint8(Result));}}));
    }
    void ShutdownModule() override {if(Proof)IConsoleManager::Get().UnregisterConsoleObject(Proof);}
};
IMPLEMENT_MODULE(FXaceAuthoringModule,XACEAuthoring)
