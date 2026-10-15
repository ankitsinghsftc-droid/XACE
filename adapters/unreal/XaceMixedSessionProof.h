// Test host only: generic actions and evidence, no package gameplay rules.
static bool WriteMixedEvidence(const FString& Transcript, const TSharedPtr<FJsonObject>& Row)
{
    FString Line=XaceCanonical::Json(Row);Line.ReplaceInline(TEXT("\r"),TEXT(""));Line.ReplaceInline(TEXT("\n"),TEXT(""));
    return FFileHelper::SaveStringToFile(Line+TEXT("\n"),*Transcript,FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM,&IFileManager::Get(),FILEWRITE_Append|FILEWRITE_AllowRead);
}
static int32 MixedSessionProof(const FString& Params)
{
    FString ConfigPath,Raw,Ticket,WorldJson;FParse::Value(*Params,TEXT("XaceMixed="),ConfigPath);
    if(!FFileHelper::LoadFileToString(Raw,*ConfigPath))return 1;
    auto Config=XaceCanonical::Parse(Raw);if(!Config)return 1;
    const FString Transcript=Config->GetStringField(TEXT("transcript"));
    bool EvidenceOk=true;
    auto Record=[&](TSharedPtr<FJsonObject> Row){if(!WriteMixedEvidence(Transcript,Row)){EvidenceOk=false;UE_LOG(LogTemp,Error,TEXT("XACE mixed proof evidence write failed: %s"),*Transcript);}};
    if(!FFileHelper::LoadFileToString(Ticket,*Config->GetStringField(TEXT("ticket")))||!FFileHelper::LoadFileToString(WorldJson,*Config->GetStringField(TEXT("world"))))return 1;
    UWorld* World=UWorld::CreateWorld(EWorldType::Game,false,TEXT("XaceMixedProof"));
    AActor* Owner=World->SpawnActor<AActor>();auto Transport=NewObject<UXaceTransportComponent>(Owner);Owner->AddInstanceComponent(Transport);Transport->RegisterComponent();Transport->bAutoConnect=false;Transport->bReconnect=false;
    auto Apply=NewObject<UXaceDeltaApplicatorComponent>(Owner);Owner->AddInstanceComponent(Apply);Apply->RegisterComponent();Apply->BindTransportNow();
    if(!Transport->ConfigureLiveSession(Ticket,WorldJson))return 1;
    Transport->ConfigureConnection(TEXT("127.0.0.1"),int32(Config->GetNumberField(TEXT("port"))),Config->GetStringField(TEXT("cgs_hash")));
    int64 Last=-1,Stop=int64(Config->GetNumberField(TEXT("stop_tick")));
    Transport->OnSessionInputTick.AddLambda([&](int64 Tick){
        const auto& Actions=Config->GetArrayField(TEXT("inputs"))[Tick]->AsArray();FXaceInputPacket Packet;Packet.Tick=Tick;Packet.PeerId=Transport->Session.PeerId;Packet.PlayerId=Transport->Session.PlayerId;Packet.SequenceId=Transport->NextSequenceId();Packet.DeviceId=TEXT("xp017-unreal");Packet.bPredicted=false;
        for(const auto& V:Actions){auto A=V->AsObject();FXaceInputAction Action;Action.Action=A->GetStringField(TEXT("action"));Action.Kind=A->GetStringField(TEXT("kind"));Action.Phase=A->GetStringField(TEXT("phase"));Action.Value=A->GetNumberField(TEXT("value"));Packet.Actions.Add(Action);}
        auto Row=MakeShared<FJsonObject>();Row->SetStringField(TEXT("kind"),Transport->SendInputPacket(Packet)?TEXT("input"):TEXT("error"));Row->SetNumberField(TEXT("tick"),Tick);Row->SetArrayField(TEXT("actions"),Actions);Record(Row);
    });
    Transport->OnJsonMessage.AddLambda([&](const TSharedPtr<FJsonObject>& M){
        const FString Kind=M->GetStringField(TEXT("msg_type"));auto Row=MakeShared<FJsonObject>();
        if(Kind==TEXT("handshake_ack")){Row->SetStringField(TEXT("kind"),TEXT("ready"));Row->SetNumberField(TEXT("player"),Transport->Session.PlayerId);Row->SetNumberField(TEXT("peer"),Transport->Session.PeerId);Row->SetObjectField(TEXT("epoch"),M->GetObjectField(TEXT("sync")));Row->SetStringField(TEXT("version"),FEngineVersion::Current().ToString());Record(Row);}
        if(Kind!=TEXT("tick_snapshot"))return;
        bool Applied=true;
        for(const auto& V:M->GetArrayField(TEXT("entities"))){auto E=V->AsObject();auto Actor=Apply->GetEntityActor(int64(E->GetNumberField(TEXT("id"))));if(!Actor){Applied=false;continue;}auto C=E->GetObjectField(TEXT("components"));auto Marker=Actor->FindComponentByClass<UXaceEntityMarkerComponent>();
            for(const auto& Pair:C->Values){FString Actual;Applied=Marker&&Marker->TryGetComponentJson(FCString::Atoi(*Pair.Key),Actual)&&Actual==Pair.Value->AsString()&&Applied;}
            if(C->HasField(TEXT("1"))){FVector Expected;auto T=XaceCanonical::Parse(C->GetStringField(TEXT("1")));Applied=XaceCanonical::Vector(T->GetObjectField(TEXT("position")),Expected)&&Actor->GetRootComponent()->GetRelativeLocation().Equals(Expected,0.01)&&Applied;}
        }
        Last=int64(M->GetNumberField(TEXT("tick")));Row->SetStringField(TEXT("kind"),TEXT("tick"));Row->SetNumberField(TEXT("tick"),Last);Row->SetBoolField(TEXT("applied"),Applied);Row->SetStringField(TEXT("projection_json"),M->GetStringField(TEXT("projection_json")));Row->SetObjectField(TEXT("sync"),M->GetObjectField(TEXT("sync")));Row->SetArrayField(TEXT("events"),M->GetArrayField(TEXT("events")));Record(Row);
    });
    Transport->ConnectToRuntime();const double Deadline=FPlatformTime::Seconds()+180;
    while(EvidenceOk&&Last<Stop&&FPlatformTime::Seconds()<Deadline){Transport->PumpOnce(0.005f);FPlatformProcess::Sleep(0.005f);}
    const bool Ok=EvidenceOk&&Last==Stop&&Transport->GetStats().ProtocolErrors==0;
    Transport->DisconnectFromRuntime(TEXT("proof leave"));auto Row=MakeShared<FJsonObject>();Row->SetStringField(TEXT("kind"),TEXT("done"));Row->SetBoolField(TEXT("ok"),Ok);Record(Row);World->DestroyWorld(false);return Ok&&EvidenceOk?0:1;
}
