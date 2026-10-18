"""Create-only file participant for reviewed native-project setup.

A registered native factory must produce and verify the staged native documents
before these files are approved. This participant is publication infrastructure,
not an engine serializer or a certification that a supplied project is playable.
Directories created during publication are retained on rollback; unique bytes are
moved to the journal by FileParticipant, never discarded.
"""
from pathlib import Path
from authoring_identity import require
from authoring_transaction_files import FileParticipant,confined,read_state


class NativeSetupFiles(FileParticipant):
    def __init__(self,root,*,engine,allowed_paths):
        require(engine in {'unity','unreal','godot'},'unsupported setup engine')
        require(Path(root).is_dir(),'setup root must already exist')
        require(type(allowed_paths) is list and 0<len(allowed_paths)<=32,'setup file limit')
        folded=[p.casefold() for p in allowed_paths if type(p) is str]
        require(len(folded)==len(allowed_paths)==len(set(folded)),'ambiguous setup paths')
        forbidden={'target','build','dist','tmp','.cache','.git','.xace','library','intermediate','saved','.godot'}
        reserved={'con','prn','aux','nul'}|{f'{p}{n}' for p in ('com','lpt') for n in range(1,10)}
        for path in allowed_paths:
            for part in path.split('/'):
                require(part==part.rstrip(' .') and not any(ord(c)<32 or c in '<>\"|?*' for c in part)
                        and part.split('.')[0].casefold() not in reserved,'Windows path alias refused')
            confined(Path(root),path)
            require(not set(path.casefold().split('/')) & forbidden,'disposable/private setup path refused')
            require(not any(other.startswith(path.casefold()+'/') for other in folded),'file/directory alias')
        super().__init__(root,name='native-setup-'+engine,allowed_paths=allowed_paths)
        self.identity['schema']='xace.native_setup_files.v1'
        self.identity['engine']=engine
        self.identity['policy']='create_only_retain_directories_on_rollback'

    def prepare(self,transaction_id,request,directory):
        # Even matching existing bytes are unowned and must not be adopted by a
        # create operation. Resume is handled by the durable participant token.
        require(type(request) is dict and type(request.get('files')) is list,'setup files required')
        require(all(type(row) is dict and row.get('before','missing') is None for row in request['files']),
                'setup cannot replace an existing file')
        require({row.get('path') for row in request['files']}==set(self.allowed),'setup write set differs from approved files')
        return super().prepare(transaction_id,request,directory)

    def _rows(self,token,directory):
        for row,path in super()._rows(token,directory):
            require(row['before'] is None,'setup token cannot overwrite existing files')
            yield row,path

    def publish(self,token,directory):
        require(self.inspect(token,directory)!='conflict','setup source conflict')
        for row,path in self._rows(token,directory):
            if read_state(path)==row['after']:continue
            # Revalidate every component before and after creating directories.
            # Never remove an existing directory, even during explicit rollback.
            confined(self.root,row['path'])
            path.parent.mkdir(parents=True,exist_ok=True)
            confined(self.root,row['path'])
        return super().publish(token,directory)
