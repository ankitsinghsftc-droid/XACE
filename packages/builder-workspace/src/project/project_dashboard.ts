/**
 * project_dashboard.ts - active project summary, New/Open/Wrap-Link project UI.
 */

const ENGINE_OPTIONS = [
  { id: 'godot', label: 'Godot' },
  { id: 'unity', label: 'Unity' },
  { id: 'unreal', label: 'Unreal' },
  { id: 'headless', label: 'Headless' },
] as const;

type EngineType = typeof ENGINE_OPTIONS[number]['id'];
type ProjectMode = 'health' | 'new' | 'open' | 'import' | 'adapter' | 'demo';

interface ProjectManifest {
  readonly name?: string;
  readonly engine_type?: string;
  readonly template_id?: string;
  readonly schema_version?: string;
  readonly cgs_path?: string;
  readonly asset_root?: string;
  readonly adapter_config?: {
    readonly engine_project_path?: string;
    readonly engine_adapter_install_path?: string;
    readonly [key: string]: unknown;
  };
  readonly updated_at_utc?: string;
}

interface ProjectInfo {
  readonly ok?: boolean;
  readonly project_dir?: string;
  readonly manifest?: ProjectManifest;
  readonly cgs_path?: string;
  readonly warnings?: string[];
  readonly error?: string;
  readonly active?: boolean;
  readonly restart_required?: boolean;
  readonly adapter_status?: AdapterStatusResult;
  readonly adapter_install_plan?: AdapterInstallPlan;
}

interface TemplateInfo {
  readonly template_id: string;
  readonly label: string;
  readonly description: string;
  readonly recommended_engines?: string[];
  readonly domains?: string[];
  readonly playable?: boolean;
}

interface TemplatesResponse {
  readonly ok?: boolean;
  readonly templates?: TemplateInfo[];
  readonly error?: string;
}

interface ProjectMutationResponse extends ProjectInfo {
  readonly manifest_path?: string;
  readonly asset_root?: string;
  readonly cgs_hash?: string;
  readonly reload_required?: boolean;
  readonly adapter_install?: AdapterInstallResult;
}

interface AdapterInstallResult {
  readonly ok?: boolean;
  readonly target?: string;
  readonly label?: string;
  readonly path?: string;
  readonly files?: string[];
  readonly skipped?: boolean;
  readonly reason?: string;
  readonly error?: string;
}

interface AdapterStatusResult {
  readonly ok?: boolean;
  readonly target?: string;
  readonly label?: string;
  readonly path?: string;
  readonly skipped?: boolean;
  readonly reason?: string;
  readonly healthy?: boolean;
  readonly installed?: boolean;
  readonly file_count?: number;
  readonly expected_count?: number;
  readonly missing_files?: string[];
  readonly error?: string;
}

interface AdapterRepairResponse {
  readonly ok?: boolean;
  readonly adapter_install?: AdapterInstallResult;
  readonly adapter_status?: AdapterStatusResult;
  readonly error?: string;
}

interface AdapterInstallPlan {
  readonly ok?: boolean;
  readonly target?: string;
  readonly label?: string;
  readonly skipped?: boolean;
  readonly reason?: string;
  readonly prepared_path?: string;
  readonly prepared_healthy?: boolean;
  readonly engine_project_path?: string;
  readonly destination_path?: string;
  readonly default_destination?: string;
  readonly steps?: string[];
  readonly error?: string;
}

interface AdapterEngineInstallResult {
  readonly ok?: boolean;
  readonly target?: string;
  readonly label?: string;
  readonly engine_project_path?: string;
  readonly destination_path?: string;
  readonly copied?: string[];
  readonly skipped?: string[];
  readonly manifest_path?: string;
  readonly steps?: string[];
  readonly reason?: string;
  readonly error?: string;
}

interface AdapterEngineInstallResponse {
  readonly ok?: boolean;
  readonly adapter_engine_install?: AdapterEngineInstallResult;
  readonly adapter_install_plan?: AdapterInstallPlan;
  readonly adapter_status?: AdapterStatusResult;
  readonly error?: string;
}

interface GodotSceneSetupResult {
  readonly ok?: boolean;
  readonly target?: string;
  readonly engine_project_path?: string;
  readonly scene_path?: string;
  readonly scene_resource?: string;
  readonly scene_created?: boolean;
  readonly scene_skipped?: boolean;
  readonly main_scene_changed?: boolean;
  readonly addon_path?: string;
  readonly error?: string;
}

interface GodotSceneSetupResponse {
  readonly ok?: boolean;
  readonly godot_scene_setup?: GodotSceneSetupResult;
  readonly adapter_install_plan?: AdapterInstallPlan;
  readonly adapter_status?: AdapterStatusResult;
  readonly error?: string;
}

interface FolderPickResponse {
  readonly ok?: boolean;
  readonly path?: string;
  readonly cancelled?: boolean;
  readonly error?: string;
}

interface DemoEngineStatus {
  readonly engine: DemoEngineKey;
  readonly label: string;
  readonly path: string;
  readonly ready: boolean;
  readonly adapter_installed: boolean;
  readonly adapter_path?: string;
  readonly reason?: string;
  readonly next_step?: string;
}

type DemoEngineKey = 'godot' | 'unity' | 'unreal';

interface DemoEngineTool {
  readonly engine: DemoEngineKey;
  readonly label: string;
  readonly detected: boolean;
  readonly executable_path: string;
  readonly candidates?: string[];
  readonly reason?: string;
}

interface ThreeEngineDemoStatus {
  readonly ok?: boolean;
  readonly project_dir?: string;
  readonly cgs_path?: string;
  readonly cgs_exists?: boolean;
  readonly runtime_bin?: string;
  readonly runtime_ready?: boolean;
  readonly runtime_status?: DemoRuntimeStatus | null;
  readonly smoke_tool?: string;
  readonly smoke_tool_ready?: boolean;
  readonly engine_tools?: DemoEngineTool[];
  readonly engines?: DemoEngineStatus[];
  readonly ready_count?: number;
  readonly adapter_installed_count?: number;
  readonly all_engine_projects_ready?: boolean;
  readonly all_adapters_installed?: boolean;
  readonly editor_free_proof_ready?: boolean;
  readonly steps?: string[];
}

interface ThreeEngineDemoResponse {
  readonly ok?: boolean;
  readonly demo?: ThreeEngineDemoStatus;
  readonly error?: string;
}

interface DemoRuntimeStatus {
  readonly ok?: boolean;
  readonly running?: boolean;
  readonly managed?: boolean;
  readonly started?: boolean;
  readonly stopped?: boolean;
  readonly already_running?: boolean;
  readonly starting?: boolean;
  readonly pid?: number | null;
  readonly returncode?: number | null;
  readonly control_endpoint?: string;
  readonly engine_port?: number;
  readonly engine_clients?: number;
  readonly runtime_bin?: string;
  readonly cgs_path?: string;
  readonly tick?: number;
  readonly alive_count?: number;
  readonly engine_connected?: boolean;
  readonly connected_engines?: DemoEngineKey[];
  readonly engine_connections?: DemoRuntimeEngineConnection[];
  readonly engine_snapshots_sent?: number;
  readonly engine_input_packets_received?: number;
  readonly engine_feedback_payloads_received?: number;
  readonly engine_feedback_messages_received?: number;
  readonly engine_malformed_messages?: number;
  readonly engine_dropped_inputs?: number;
  readonly adapter_type?: string;
  readonly paused?: boolean;
  readonly snapshot_tick?: number;
  readonly snapshot_hash?: string;
  readonly state_hash?: string;
  readonly reason?: string;
  readonly error?: string;
}

interface DemoRuntimeEngineConnection {
  readonly engine: DemoEngineKey;
  readonly label: string;
  readonly connected: boolean;
  readonly tick?: number | null;
  readonly snapshot_hash?: string;
  readonly snapshots_sent?: number;
  readonly input_packets_received?: number;
  readonly feedback_payloads_received?: number;
  readonly feedback_messages_received?: number;
  readonly malformed_messages?: number;
  readonly dropped_inputs?: number;
  readonly queued_inputs?: number;
  readonly queued_feedback?: number;
}

interface DemoRuntimeResponse {
  readonly ok?: boolean;
  readonly runtime?: DemoRuntimeStatus;
  readonly error?: string;
}

interface LiveValidationStep {
  readonly id?: string;
  readonly label?: string;
  readonly ok?: boolean;
  readonly detail?: string;
}

interface LiveValidationEngine {
  readonly engine: DemoEngineKey;
  readonly label: string;
  readonly ready?: boolean;
  readonly connected?: boolean;
  readonly next_step?: string;
  readonly steps?: LiveValidationStep[];
}

interface LiveValidationStatus {
  readonly ok?: boolean;
  readonly runtime?: DemoRuntimeStatus;
  readonly passed_count?: number;
  readonly engine_count?: number;
  readonly summary?: string;
  readonly next_step?: string;
  readonly engines?: LiveValidationEngine[];
  readonly unreal_prerequisite?: {
    readonly ok?: boolean;
    readonly detected?: boolean;
    readonly label?: string;
    readonly version?: string;
    readonly path?: string;
    readonly reason?: string;
    readonly next_step?: string;
  };
}

interface LiveValidationResponse extends ThreeEngineDemoResponse {
  readonly live_validation?: LiveValidationStatus;
}

interface DemoSessionLaunch {
  readonly ok?: boolean;
  readonly skipped?: boolean;
  readonly engine?: DemoEngineKey;
  readonly label?: string;
  readonly engine_project_path?: string;
  readonly executable_path?: string;
  readonly reason?: string;
  readonly error?: string;
}

interface DemoSessionStartResponse extends ThreeEngineDemoResponse {
  readonly runtime?: DemoRuntimeStatus;
  readonly launches?: DemoSessionLaunch[];
  readonly engine_tools?: DemoEngineTool[];
}

interface ThreeEngineSmokeResponse extends ThreeEngineDemoResponse {
  readonly smoke?: {
    readonly ok?: boolean;
    readonly stdout?: string;
    readonly stderr?: string;
    readonly error?: string;
    readonly result?: {
      readonly clients?: number;
      readonly cgs_hash?: string;
      readonly state_hash?: string;
      readonly tick?: number;
      readonly adapter_type?: string;
      readonly ok?: boolean;
    };
  };
}

interface MultiplayerSmokeStep {
  readonly id?: string;
  readonly label?: string;
  readonly ok?: boolean;
  readonly detail?: string;
}

interface MultiplayerSmokeResult {
  readonly ok?: boolean;
  readonly command?: string[];
  readonly returncode?: number;
  readonly stdout?: string;
  readonly stderr?: string;
  readonly error?: string;
  readonly steps?: MultiplayerSmokeStep[];
}

interface MultiplayerSmokeResponse {
  readonly ok?: boolean;
  readonly smoke?: MultiplayerSmokeResult;
  readonly error?: string;
}

interface CertificationStatusResult {
  readonly ok?: boolean;
  readonly tool?: string;
  readonly tool_ready?: boolean;
  readonly npm_script_ready?: boolean;
  readonly command?: string[];
  readonly label?: string;
  readonly detail?: string;
  readonly error?: string;
}

interface CertificationStep {
  readonly label?: string;
  readonly ok?: boolean;
  readonly detail?: string;
}

interface CertificationRunResult {
  readonly ok?: boolean;
  readonly command?: string[];
  readonly returncode?: number;
  readonly stdout?: string;
  readonly stderr?: string;
  readonly error?: string;
  readonly status?: CertificationStatusResult;
  readonly steps?: CertificationStep[];
}

interface CertificationStatusResponse {
  readonly ok?: boolean;
  readonly certification?: CertificationStatusResult;
  readonly error?: string;
}

interface CertificationRunResponse {
  readonly ok?: boolean;
  readonly certification?: CertificationRunResult;
  readonly error?: string;
}

interface DemoEngineToolsResponse {
  readonly ok?: boolean;
  readonly engine_tools?: DemoEngineTool[];
  readonly error?: string;
}

interface DemoLaunchResponse {
  readonly ok?: boolean;
  readonly launch?: {
    readonly ok?: boolean;
    readonly engine?: DemoEngineKey;
    readonly label?: string;
    readonly engine_project_path?: string;
    readonly executable_path?: string;
    readonly error?: string;
  };
  readonly error?: string;
}

interface NewProjectForm {
  engineType: EngineType;
  templateId: string;
  name: string;
  projectPath: string;
  force: boolean;
}

interface ImportProjectForm {
  engineType: EngineType;
  templateId: string;
  name: string;
  engineProjectPath: string;
  xaceProjectPath: string;
  force: boolean;
}

interface AdapterEngineInstallForm {
  engineProjectPath: string;
  overwrite: boolean;
  setMainScene: boolean;
}

interface ThreeEngineDemoForm {
  godotPath: string;
  unityPath: string;
  unrealPath: string;
  godotExe: string;
  unityExe: string;
  unrealExe: string;
  savePaths: boolean;
}

interface RecentProject {
  readonly name: string;
  readonly path: string;
  readonly engine: string;
  readonly timestamp: number;
}

const RECENT_KEY = 'xace.recentProjects';

const STYLES = `
.xb-pd-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,.64);
  display: flex; align-items: center; justify-content: center;
  z-index: 950; backdrop-filter: blur(4px);
}
.xb-pd-modal {
  width: 760px; max-width: 94vw; max-height: 88vh;
  background: var(--bgc); border: 1px solid var(--bdh); border-radius: var(--rl);
  display: flex; flex-direction: column; overflow: hidden; animation: fade-in 150ms ease-out;
}
.xb-pd-head {
  padding: 12px 14px 10px; border-bottom: 1px solid var(--bd);
  display: flex; align-items: center; gap: 8px;
}
.xb-pd-title { flex: 1; font-size: 13px; font-weight: 700; color: var(--txt); }
.xb-pd-close {
  width: 24px; height: 24px; border: none; background: transparent;
  color: var(--txt2); border-radius: 3px; cursor: pointer; font-size: 16px;
  line-height: 1; font-family: inherit;
}
.xb-pd-close:hover { background: rgba(255,255,255,.05); color: var(--txt); }
.xb-pd-body {
  overflow-y: auto; padding: 12px 14px; display: grid;
  grid-template-columns: minmax(0, .9fr) minmax(0, 1.35fr); gap: 12px;
}
.xb-pd-section {
  border: 1px solid var(--bd); border-radius: var(--r); background: var(--bgp);
  min-width: 0; overflow: hidden;
}
.xb-pd-section-head {
  padding: 8px 10px; border-bottom: 1px solid var(--bd);
  display: flex; align-items: center; gap: 8px;
}
.xb-pd-section-title {
  flex: 1; font-size: 9px; font-weight: 700; letter-spacing: .12em;
  text-transform: uppercase; color: var(--txt2);
}
.xb-pd-content { padding: 10px; }
.xb-pd-kv {
  display: grid; grid-template-columns: 76px minmax(0, 1fr);
  gap: 5px 8px; font-size: 10px; line-height: 1.45;
}
.xb-pd-k {
  color: var(--txt3); font-size: 9px; text-transform: uppercase; letter-spacing: .08em;
}
.xb-pd-v { color: var(--txt2); min-width: 0; overflow-wrap: anywhere; }
.xb-pd-v strong { color: var(--txt); font-weight: 600; }
.xb-pd-warn { margin-top: 8px; color: var(--amb); font-size: 9.5px; line-height: 1.45; }
.xb-pd-adapter-actions {
  margin-top: 8px; display: flex; align-items: center; gap: 7px; flex-wrap: wrap;
}
.xb-pd-adapter-pill {
  color: var(--txt3); font-size: 9.5px; line-height: 1.4; overflow-wrap: anywhere;
}
.xb-pd-adapter-pill.ok { color: var(--grn); }
.xb-pd-adapter-pill.warn { color: var(--amb); }
.xb-pd-repair {
  border: 1px solid var(--bd); background: rgba(255,255,255,.035);
  border-radius: var(--rs); color: var(--txt2); cursor: pointer;
  font-family: inherit; font-size: 10px; padding: 5px 8px; white-space: nowrap;
}
.xb-pd-repair:hover { border-color: rgba(0,212,255,.3); color: var(--cyan); }
.xb-pd-repair:disabled { opacity: .55; cursor: default; }
.xb-pd-tabs {
  display: grid; grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 3px; padding: 8px 10px; border-bottom: 1px solid var(--bd);
}
.xb-pd-tab {
  border: 1px solid var(--bd); background: rgba(255,255,255,.03);
  border-radius: var(--rs); color: var(--txt2); cursor: pointer;
  font-family: inherit; font-size: 10px; font-weight: 700; padding: 5px 4px;
}
.xb-pd-tab.on {
  border-color: rgba(0,212,255,.36); background: var(--cynd); color: var(--cyan);
}
.xb-pd-form { display: flex; flex-direction: column; gap: 9px; }
.xb-pd-row { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.xb-pd-label {
  font-size: 9px; font-weight: 700; letter-spacing: .1em;
  text-transform: uppercase; color: var(--txt2);
}
.xb-pd-input,
.xb-pd-select {
  width: 100%; background: rgba(255,255,255,.035); border: 1px solid var(--bd);
  border-radius: var(--rs); color: var(--txt); padding: 6px 8px; font-size: 11px;
  font-family: inherit; outline: none; box-sizing: border-box;
}
.xb-pd-input:focus,
.xb-pd-select:focus { border-color: var(--cyan); }
.xb-pd-path-row { display: flex; gap: 5px; align-items: center; }
.xb-pd-path-row .xb-pd-input { flex: 1; min-width: 0; }
.xb-pd-browse {
  border: 1px solid var(--bd); background: rgba(255,255,255,.035);
  border-radius: var(--rs); color: var(--txt2); cursor: pointer;
  font-family: inherit; font-size: 10px; padding: 6px 9px; white-space: nowrap;
}
.xb-pd-browse:hover { border-color: rgba(0,212,255,.3); color: var(--cyan); }
.xb-pd-engines { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 4px; }
.xb-pd-engine {
  border: 1px solid var(--bd); background: rgba(255,255,255,.03);
  border-radius: var(--rs); color: var(--txt2); font-size: 10px;
  padding: 5px 4px; cursor: pointer; font-family: inherit;
}
.xb-pd-engine.on {
  border-color: rgba(0,212,255,.36); background: var(--cynd); color: var(--cyan);
}
.xb-pd-template-meta,
.xb-pd-note { color: var(--txt3); font-size: 9.5px; line-height: 1.45; }
.xb-pd-note strong { color: var(--txt2); font-weight: 600; }
.xb-pd-steps {
  margin: 0; padding-left: 16px; color: var(--txt3); font-size: 9.5px; line-height: 1.5;
}
.xb-pd-steps li { margin: 2px 0; }
.xb-pd-demo-list { display: flex; flex-direction: column; gap: 6px; }
.xb-pd-demo-item {
  border: 1px solid var(--bd); border-radius: var(--rs);
  background: rgba(255,255,255,.025); padding: 7px 8px;
}
.xb-pd-demo-top { display: flex; align-items: center; gap: 8px; }
.xb-pd-demo-name { flex: 1; color: var(--txt); font-size: 11px; font-weight: 700; }
.xb-pd-demo-badge { font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: .08em; }
.xb-pd-demo-badge.ok { color: var(--grn); }
.xb-pd-demo-badge.warn { color: var(--amb); }
.xb-pd-demo-detail { margin-top: 4px; color: var(--txt3); font-size: 9.5px; line-height: 1.45; overflow-wrap: anywhere; }
.xb-pd-demo-actions { margin-top: 6px; display: flex; gap: 6px; flex-wrap: wrap; }
.xb-pd-inline-actions { display: flex; gap: 7px; flex-wrap: wrap; }
.xb-pd-check {
  display: flex; gap: 7px; align-items: flex-start; color: var(--txt2);
  font-size: 10px; line-height: 1.45;
}
.xb-pd-check input { margin-top: 1px; }
.xb-pd-recent {
  margin-top: 10px; padding-top: 9px; border-top: 1px solid var(--bd);
  display: flex; flex-direction: column; gap: 5px;
}
.xb-pd-recent-title {
  font-size: 9px; font-weight: 700; color: var(--txt2); letter-spacing: .1em;
  text-transform: uppercase;
}
.xb-pd-recent-btn {
  text-align: left; border: 1px solid var(--bd); background: rgba(255,255,255,.025);
  border-radius: var(--rs); color: var(--txt2); cursor: pointer; font-family: inherit;
  font-size: 10px; padding: 5px 7px; overflow-wrap: anywhere;
}
.xb-pd-recent-btn:hover { border-color: rgba(0,212,255,.3); color: var(--cyan); }
.xb-pd-actions {
  display: flex; align-items: center; justify-content: flex-end; gap: 8px;
  padding: 10px 14px; border-top: 1px solid var(--bd);
}
.xb-pd-status {
  flex: 1; min-width: 0; color: var(--txt3); font-size: 10px;
  line-height: 1.4; overflow-wrap: anywhere;
}
.xb-pd-status.ok { color: var(--grn); }
.xb-pd-status.err { color: var(--red); }
.xb-pd-cancel,
.xb-pd-primary {
  border-radius: var(--rs); font-size: 11px; padding: 6px 13px;
  cursor: pointer; font-family: inherit;
}
.xb-pd-cancel {
  background: rgba(255,255,255,.035); border: 1px solid var(--bd); color: var(--txt2);
}
.xb-pd-cancel:hover { border-color: var(--bdh); color: var(--txt); }
.xb-pd-primary {
  background: var(--cynd); border: 1px solid rgba(0,212,255,.34);
  color: var(--cyan); font-weight: 700;
}
.xb-pd-primary:disabled { opacity: .55; cursor: default; }
@media (max-width: 780px) {
  .xb-pd-body { grid-template-columns: 1fr; }
  .xb-pd-engines { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
`;

export class ProjectDashboard {
  private _overlay: HTMLElement | null = null;
  private _activeInfo: ProjectInfo | null = null;
  private _templates: TemplateInfo[] = [];
  private _recent: RecentProject[] = [];
  private _mode: ProjectMode = 'health';
  private _loading = false;
  private _busy = false;

  private _newForm: NewProjectForm = {
    engineType: 'godot',
    templateId: 'blank_3d',
    name: 'New XACE Project',
    projectPath: './project',
    force: false,
  };
  private _openPath = '';
  private _importForm: ImportProjectForm = {
    engineType: 'godot',
    templateId: 'blank_3d',
    name: 'Imported XACE Project',
    engineProjectPath: '',
    xaceProjectPath: './imported-xace-project',
    force: false,
  };
  private _adapterForm: AdapterEngineInstallForm = {
    engineProjectPath: '',
    overwrite: false,
    setMainScene: false,
  };
  private _demoForm: ThreeEngineDemoForm = {
    godotPath: '',
    unityPath: '',
    unrealPath: '',
    godotExe: '',
    unityExe: '',
    unrealExe: '',
    savePaths: true,
  };
  private _lastDemoStatus: ThreeEngineDemoStatus | null = null;
  private _engineTools: DemoEngineTool[] = [];
  private _demoRuntimeStatus: DemoRuntimeStatus | null = null;
  private _lastLiveValidation: LiveValidationStatus | null = null;
  private _lastMultiplayerSmoke: MultiplayerSmokeResult | null = null;
  private _certificationStatus: CertificationStatusResult | null = null;
  private _lastCertification: CertificationRunResult | null = null;

  private _activeEl!: HTMLElement;
  private _tabsEl!: HTMLElement;
  private _actionEl!: HTMLElement;
  private _statusEl!: HTMLElement;
  private _primaryBtn!: HTMLButtonElement;

  constructor() {
    this._injectStyles();
  }

  open(mode?: ProjectMode): void {
    if (mode) {
      this._mode = mode;
    }
    if (this._overlay) {
      this._render();
      return;
    }

    this._recent = loadRecentProjects();
    this._overlay = el('div', 'xb-pd-overlay');
    this._overlay.appendChild(this._buildModal());
    document.body.appendChild(this._overlay);
    this._overlay.addEventListener('click', (event) => {
      if (event.target === this._overlay) this.close();
    });
    this._load();
  }

  close(): void {
    this._overlay?.remove();
    this._overlay = null;
  }

  private _buildModal(): HTMLElement {
    const modal = el('div', 'xb-pd-modal');

    const head = el('div', 'xb-pd-head');
    head.appendChild(el('div', 'xb-pd-title', { textContent: 'Project Dashboard' }));
    const closeBtn = el('button', 'xb-pd-close', { textContent: 'x', title: 'Close' });
    closeBtn.addEventListener('click', () => this.close());
    head.appendChild(closeBtn);
    modal.appendChild(head);

    const body = el('div', 'xb-pd-body');
    body.appendChild(this._buildActiveSection());
    body.appendChild(this._buildActionSection());
    modal.appendChild(body);

    const actions = el('div', 'xb-pd-actions');
    this._statusEl = el('div', 'xb-pd-status', { textContent: 'Loading project details...' });
    actions.appendChild(this._statusEl);

    const cancel = el('button', 'xb-pd-cancel', { textContent: 'Close' });
    cancel.addEventListener('click', () => this.close());
    actions.appendChild(cancel);

    this._primaryBtn = el('button', 'xb-pd-primary') as HTMLButtonElement;
    this._primaryBtn.addEventListener('click', () => this._runPrimaryAction());
    actions.appendChild(this._primaryBtn);
    modal.appendChild(actions);

    this._render();
    return modal;
  }

  private _buildActiveSection(): HTMLElement {
    const section = el('section', 'xb-pd-section');
    const head = el('div', 'xb-pd-section-head');
    head.appendChild(el('div', 'xb-pd-section-title', { textContent: 'Active Project' }));
    section.appendChild(head);

    this._activeEl = el('div', 'xb-pd-content');
    section.appendChild(this._activeEl);
    return section;
  }

  private _buildActionSection(): HTMLElement {
    const section = el('section', 'xb-pd-section');
    this._tabsEl = el('div', 'xb-pd-tabs');
    section.appendChild(this._tabsEl);
    this._actionEl = el('div', 'xb-pd-content');
    section.appendChild(this._actionEl);
    return section;
  }

  private async _load(): Promise<void> {
    this._loading = true;
    this._setStatus('Loading project details...', '');
    this._render();

    try {
      const [project, templates] = await Promise.all([
        fetchJson<ProjectInfo>('/api/project'),
        fetchJson<TemplatesResponse>('/api/project/templates'),
      ]);
      this._activeInfo = project;
      if (templates.ok === false) {
        throw new Error(templates.error || 'Template list failed to load.');
      }
      this._templates = templates.templates ?? [];
      this._seedFormsFromActiveProject();
      this._setStatus('Ready.', '');
    } catch (error) {
      this._setStatus(readError(error), 'err');
    } finally {
      this._loading = false;
      this._render();
    }
  }

  private _seedFormsFromActiveProject(): void {
    const manifest = this._activeInfo?.manifest;
    const engine = parseEngine(manifest?.engine_type);
    const templateId = pickTemplateId(this._templates, manifest?.template_id);
    const projectDir = this._activeInfo?.project_dir ?? './project';
    const newName = manifest?.name ? `${manifest.name} Copy` : 'New XACE Project';

    this._newForm = {
      engineType: engine,
      templateId,
      name: newName,
      projectPath: suggestNewProjectPath(projectDir, newName),
      force: false,
    };
    this._openPath = projectDir;
    this._importForm = {
      engineType: engine,
      templateId,
      name: 'Imported XACE Project',
      engineProjectPath: '',
      xaceProjectPath: projectDir,
      force: false,
    };
    this._adapterForm = {
      engineProjectPath: manifest?.adapter_config?.engine_project_path ?? '',
      overwrite: false,
      setMainScene: false,
    };
    const demoProjects = readDemoEngineProjects(manifest?.adapter_config?.demo_engine_projects);
    this._demoForm = {
      godotPath: demoProjects.godot,
      unityPath: demoProjects.unity,
      unrealPath: demoProjects.unreal,
      godotExe: '',
      unityExe: '',
      unrealExe: '',
      savePaths: true,
    };
  }

  private _render(): void {
    if (!this._overlay) return;
    this._renderActiveProject();
    this._renderTabs();
    this._renderAction();
    this._primaryBtn.textContent = primaryLabel(this._mode);
    this._primaryBtn.disabled = this._loading || this._busy;
  }

  private _renderActiveProject(): void {
    const info = this._activeInfo;
    if (!info) {
      this._activeEl.innerHTML = `<div class="xb-pd-kv"><div class="xb-pd-k">Status</div><div class="xb-pd-v">Loading...</div></div>`;
      return;
    }

    if (info.ok === false) {
      this._activeEl.innerHTML = `
        <div class="xb-pd-kv">
          <div class="xb-pd-k">Folder</div><div class="xb-pd-v">${escapeHtml(info.project_dir ?? '')}</div>
          <div class="xb-pd-k">Status</div><div class="xb-pd-v"><strong>Not opened as a XACE project</strong></div>
        </div>
        <div class="xb-pd-warn">${escapeHtml(info.error ?? 'No project manifest was found.')}</div>
      `;
      this._appendRecentProjects();
      return;
    }

    const manifest = info.manifest ?? {};
    const warnings = info.warnings ?? [];
    const adapterStatus = info.adapter_status;
    this._activeEl.innerHTML = `
      <div class="xb-pd-kv">
        <div class="xb-pd-k">Name</div><div class="xb-pd-v"><strong>${escapeHtml(manifest.name ?? 'Untitled')}</strong></div>
        <div class="xb-pd-k">Engine</div><div class="xb-pd-v">${escapeHtml(labelForEngine(manifest.engine_type))}</div>
        <div class="xb-pd-k">Template</div><div class="xb-pd-v">${escapeHtml(templateLabel(this._templates, manifest.template_id))}</div>
        <div class="xb-pd-k">Folder</div><div class="xb-pd-v">${escapeHtml(info.project_dir ?? '')}</div>
        <div class="xb-pd-k">CGS</div><div class="xb-pd-v">${escapeHtml(info.cgs_path ?? manifest.cgs_path ?? 'game.cgs.json')}</div>
        <div class="xb-pd-k">Assets</div><div class="xb-pd-v">${escapeHtml(manifest.asset_root ?? 'assets')}</div>
        <div class="xb-pd-k">Adapter</div><div class="xb-pd-v">${escapeHtml(adapterStatusSummary(adapterStatus, manifest.engine_type))}</div>
      </div>
      ${warnings.length > 0 ? `<div class="xb-pd-warn">${escapeHtml(warnings.join(' '))}</div>` : ''}
    `;
    this._appendAdapterActions(adapterStatus, manifest.engine_type);
    this._appendRecentProjects();
  }

  private _appendAdapterActions(
    adapterStatus: AdapterStatusResult | undefined,
    engineType: string | undefined,
  ): void {
    if (!adapterStatus || adapterStatus.skipped || engineType === 'headless') return;
    const wrap = el('div', 'xb-pd-adapter-actions');
    const statusKind = adapterStatus.healthy ? 'ok' : 'warn';
    wrap.appendChild(el('div', `xb-pd-adapter-pill ${statusKind}`, {
      textContent: adapterStatus.healthy ? 'Adapter is ready.' : 'Adapter needs repair.',
    }));
    const repair = el('button', 'xb-pd-repair', {
      textContent: adapterStatus.healthy ? 'Reinstall Adapter' : 'Repair Adapter',
      type: 'button',
    }) as HTMLButtonElement;
    repair.disabled = this._busy;
    repair.addEventListener('click', () => this._repairAdapter());
    wrap.appendChild(repair);

    const install = el('button', 'xb-pd-repair', {
      textContent: 'Copy To Engine',
      type: 'button',
    }) as HTMLButtonElement;
    install.disabled = this._busy;
    install.addEventListener('click', () => {
      this._mode = 'adapter';
      this._render();
      this._setStatus('Choose the engine project folder, then click Copy Adapter.', '');
    });
    wrap.appendChild(install);
    this._activeEl.appendChild(wrap);
  }

  private _appendRecentProjects(): void {
    if (this._recent.length === 0) return;
    const recentEl = el('div', 'xb-pd-recent');
    recentEl.appendChild(el('div', 'xb-pd-recent-title', { textContent: 'Recent Projects' }));
    for (const item of this._recent.slice(0, 4)) {
      const btn = el('button', 'xb-pd-recent-btn', {
        textContent: `${item.name} - ${item.path}`,
        title: item.path,
      });
      btn.addEventListener('click', () => {
        this._mode = 'open';
        this._openPath = item.path;
        this._render();
        this._setStatus('Recent project selected. Click Open Project to validate it.', '');
      });
      recentEl.appendChild(btn);
    }
    this._activeEl.appendChild(recentEl);
  }

  private _renderTabs(): void {
    this._tabsEl.innerHTML = '';
    for (const mode of ['health', 'new', 'open', 'import', 'adapter', 'demo'] as ProjectMode[]) {
      const tab = el('button', `xb-pd-tab${this._mode === mode ? ' on' : ''}`, {
        textContent: tabLabel(mode),
      });
      tab.addEventListener('click', () => {
        this._mode = mode;
        this._render();
        this._setStatus('Ready.', '');
      });
      this._tabsEl.appendChild(tab);
    }
  }

  private _renderAction(): void {
    this._actionEl.innerHTML = '';
    if (this._mode === 'health') {
      this._actionEl.appendChild(this._buildHealthForm());
    } else if (this._mode === 'new') {
      this._actionEl.appendChild(this._buildNewForm());
    } else if (this._mode === 'open') {
      this._actionEl.appendChild(this._buildOpenForm());
    } else if (this._mode === 'import') {
      this._actionEl.appendChild(this._buildImportForm());
    } else if (this._mode === 'adapter') {
      this._actionEl.appendChild(this._buildAdapterInstallForm());
    } else {
      this._actionEl.appendChild(this._buildThreeEngineDemoForm());
    }
  }

  private _buildHealthForm(): HTMLElement {
    const form = el('div', 'xb-pd-form');
    form.appendChild(el('div', 'xb-pd-note', {
      textContent: 'Launch health checks the active project, adapter setup, runtime proof command, and quick certification path without opening engine editors.',
    }));

    const actions = el('div', 'xb-pd-inline-actions');
    const refresh = el('button', 'xb-pd-browse', {
      textContent: 'Refresh Health',
      type: 'button',
    }) as HTMLButtonElement;
    refresh.disabled = this._busy;
    refresh.addEventListener('click', () => this._checkLaunchHealth());
    actions.appendChild(refresh);

    const certify = el('button', 'xb-pd-primary', {
      textContent: 'Run Quick Certification',
      type: 'button',
    }) as HTMLButtonElement;
    certify.disabled = this._busy;
    certify.addEventListener('click', () => this._runQuickCertification());
    actions.appendChild(certify);
    form.appendChild(actions);

    form.appendChild(this._buildHealthStatus());
    if (this._lastCertification) {
      form.appendChild(this._buildCertificationResult(this._lastCertification));
    }
    return form;
  }

  private _buildHealthStatus(): HTMLElement {
    const wrap = el('div', 'xb-pd-demo-list');
    const info = this._activeInfo;
    const manifest = info?.manifest;
    wrap.appendChild(demoItem(
      'Active project',
      Boolean(info?.ok && manifest),
      info?.ok && manifest
        ? `${manifest.name ?? 'XACE Project'} (${labelForEngine(manifest.engine_type)}) at ${info.project_dir ?? ''}`
        : info?.error ?? 'No active XACE project loaded.',
    ));
    wrap.appendChild(demoItem(
      'CGS file',
      Boolean(info?.cgs_path),
      info?.cgs_path ? `Using ${info.cgs_path}` : 'No CGS path reported yet.',
    ));
    wrap.appendChild(demoItem(
      'Project adapter',
      Boolean(info?.adapter_status?.healthy || info?.adapter_status?.skipped),
      adapterStatusSummary(info?.adapter_status, manifest?.engine_type),
    ));
    const cert = this._certificationStatus;
    wrap.appendChild(demoItem(
      'Certification command',
      Boolean(cert?.ok),
      cert
        ? `${cert.detail ?? ''} ${cert.command ? `Command: ${commandText(cert.command)}` : ''}`.trim()
        : 'Not checked yet. Click Refresh Health.',
    ));
    return wrap;
  }

  private _buildCertificationResult(result: CertificationRunResult): HTMLElement {
    const wrap = el('div', 'xb-pd-demo-list');
    wrap.appendChild(demoItem(
      'Quick certification result',
      Boolean(result.ok),
      result.ok
        ? `${result.steps?.filter(step => step.ok).length ?? 0}/${result.steps?.length ?? 0} checks passed.`
        : result.error || 'Quick certification failed.',
    ));
    for (const step of result.steps ?? []) {
      wrap.appendChild(demoItem(
        step.label ?? 'Certification check',
        Boolean(step.ok),
        step.detail ?? '',
      ));
    }
    return wrap;
  }

  private _buildNewForm(): HTMLElement {
    const form = el('div', 'xb-pd-form');
    form.appendChild(this._buildEngineRow(this._newForm.engineType, engine => {
      this._newForm.engineType = engine;
      this._render();
    }));
    form.appendChild(this._buildTemplateRow(this._newForm.templateId, this._newForm.engineType, templateId => {
      this._newForm.templateId = templateId;
      this._render();
    }));
    form.appendChild(this._buildInputRow('Project Name', this._newForm.name, 'My XACE Game', value => {
      this._newForm.name = value;
    }));
    form.appendChild(this._buildInputRow(
      'Project Folder',
      this._newForm.projectPath,
      'C:\\path\\to\\my-project',
      value => { this._newForm.projectPath = value; },
      { title: 'Choose XACE project folder' },
    ));
    form.appendChild(this._buildForceRow(this._newForm.force, value => {
      this._newForm.force = value;
    }));
    return form;
  }

  private _buildOpenForm(): HTMLElement {
    const form = el('div', 'xb-pd-form');
    form.appendChild(this._buildInputRow(
      'Project Folder',
      this._openPath,
      'C:\\path\\to\\xace-project',
      value => { this._openPath = value; },
      { title: 'Choose XACE project folder' },
    ));
    form.appendChild(el('div', 'xb-pd-note', {
      textContent: 'Open validates an existing XACE folder, switches Builder to it, and reloads the UI automatically.',
    }));
    return form;
  }

  private _buildImportForm(): HTMLElement {
    const form = el('div', 'xb-pd-form');
    form.appendChild(this._buildEngineRow(this._importForm.engineType, engine => {
      this._importForm.engineType = engine;
      this._render();
    }));
    form.appendChild(this._buildTemplateRow(this._importForm.templateId, this._importForm.engineType, templateId => {
      this._importForm.templateId = templateId;
      this._render();
    }));
    form.appendChild(this._buildInputRow('Project Name', this._importForm.name, 'Imported XACE Project', value => {
      this._importForm.name = value;
    }));
    form.appendChild(this._buildInputRow(
      'Engine Project Folder',
      this._importForm.engineProjectPath,
      'C:\\path\\to\\godot-or-unity-project',
      value => { this._importForm.engineProjectPath = value; },
      { title: 'Choose engine project folder' },
    ));
    form.appendChild(this._buildInputRow(
      'XACE Project Folder',
      this._importForm.xaceProjectPath,
      'C:\\path\\to\\xace-wrapper',
      value => { this._importForm.xaceProjectPath = value; },
      { title: 'Choose XACE wrapper folder' },
    ));
    form.appendChild(el('div', 'xb-pd-note', {
      textContent: 'Wrap/link creates a XACE manifest, starter CGS, and adapter preparation around an engine project. It does not convert existing engine gameplay into CGS.',
    }));
    form.appendChild(this._buildForceRow(this._importForm.force, value => {
      this._importForm.force = value;
    }));
    return form;
  }

  private _buildAdapterInstallForm(): HTMLElement {
    const form = el('div', 'xb-pd-form');
    const manifest = this._activeInfo?.manifest;
    const engineType = parseEngine(manifest?.engine_type);
    const plan = this._activeInfo?.adapter_install_plan;

    if (engineType === 'headless') {
      form.appendChild(el('div', 'xb-pd-note', {
        textContent: 'Headless projects do not need an engine adapter.',
      }));
      return form;
    }

    const preparedNote = el('div', 'xb-pd-note');
    preparedNote.innerHTML = `<strong>Prepared adapter:</strong> ${escapeHtml(plan?.prepared_path ?? 'Not checked yet.')}`;
    form.appendChild(preparedNote);
    const destinationNote = el('div', 'xb-pd-note');
    destinationNote.innerHTML = `<strong>Destination:</strong> ${escapeHtml(plan?.destination_path || plan?.default_destination || 'Choose an engine project folder.')}`;
    form.appendChild(destinationNote);
    form.appendChild(this._buildInputRow(
      'Engine Project Folder',
      this._adapterForm.engineProjectPath,
      engineProjectPlaceholder(engineType),
      value => { this._adapterForm.engineProjectPath = value; },
      { title: `Choose ${labelForEngine(engineType)} project folder` },
    ));
    form.appendChild(this._buildOverwriteRow(this._adapterForm.overwrite, value => {
      this._adapterForm.overwrite = value;
    }));
    if (engineType === 'godot') {
      form.appendChild(this._buildSetMainSceneRow(this._adapterForm.setMainScene, value => {
        this._adapterForm.setMainScene = value;
      }));
      const sceneActions = el('div', 'xb-pd-inline-actions');
      const setupScene = el('button', 'xb-pd-browse', {
        textContent: 'Setup Godot Scene',
        type: 'button',
      }) as HTMLButtonElement;
      setupScene.disabled = this._busy;
      setupScene.addEventListener('click', () => this._setupGodotScene());
      sceneActions.appendChild(setupScene);
      form.appendChild(sceneActions);
    }
    const steps = plan?.steps ?? adapterInstallSteps(engineType);
    const list = el('ol', 'xb-pd-steps');
    for (const step of steps) {
      list.appendChild(el('li', '', { textContent: step }));
    }
    form.appendChild(list);
    return form;
  }

  private _buildThreeEngineDemoForm(): HTMLElement {
    const form = el('div', 'xb-pd-form');
    form.appendChild(el('div', 'xb-pd-note', {
      textContent: 'Prepare the video demo: one XACE runtime feeds Godot, Unity, and Unreal. This page checks folders and can run the editor-free proof without opening the engines.',
    }));
    form.appendChild(this._buildInputRow(
      'Godot Project Folder',
      this._demoForm.godotPath,
      engineProjectPlaceholder('godot'),
      value => { this._demoForm.godotPath = value; },
      { title: 'Choose Godot project folder' },
    ));
    form.appendChild(this._buildInputRow(
      'Unity Project Folder',
      this._demoForm.unityPath,
      engineProjectPlaceholder('unity'),
      value => { this._demoForm.unityPath = value; },
      { title: 'Choose Unity project folder' },
    ));
    form.appendChild(this._buildInputRow(
      'Unreal Project Folder',
      this._demoForm.unrealPath,
      engineProjectPlaceholder('unreal'),
      value => { this._demoForm.unrealPath = value; },
      { title: 'Choose Unreal project folder' },
    ));
    form.appendChild(el('div', 'xb-pd-note', {
      textContent: 'Optional: paste an engine executable path if Builder cannot detect it automatically.',
    }));
    form.appendChild(this._buildInputRow(
      'Godot Executable',
      this._demoForm.godotExe,
      detectedExecutable(this._engineTools, 'godot') || 'Leave blank to auto-detect Godot',
      value => { this._demoForm.godotExe = value; },
    ));
    form.appendChild(this._buildInputRow(
      'Unity Executable',
      this._demoForm.unityExe,
      detectedExecutable(this._engineTools, 'unity') || 'Leave blank to auto-detect Unity',
      value => { this._demoForm.unityExe = value; },
    ));
    form.appendChild(this._buildInputRow(
      'Unreal Executable',
      this._demoForm.unrealExe,
      detectedExecutable(this._engineTools, 'unreal') || 'Leave blank to auto-detect Unreal',
      value => { this._demoForm.unrealExe = value; },
    ));
    form.appendChild(this._buildSaveDemoPathsRow(this._demoForm.savePaths, value => {
      this._demoForm.savePaths = value;
    }));

    const actions = el('div', 'xb-pd-inline-actions');
    const startSession = el('button', 'xb-pd-primary', {
      textContent: 'Start Session',
      type: 'button',
    }) as HTMLButtonElement;
    startSession.disabled = this._busy;
    startSession.addEventListener('click', () => this._startDemoSession());
    actions.appendChild(startSession);
    const startRuntime = el('button', 'xb-pd-browse', {
      textContent: 'Start Runtime',
      type: 'button',
    }) as HTMLButtonElement;
    startRuntime.disabled = this._busy;
    startRuntime.addEventListener('click', () => this._startDemoRuntime());
    actions.appendChild(startRuntime);
    const checkRuntime = el('button', 'xb-pd-browse', {
      textContent: 'Check Runtime',
      type: 'button',
    }) as HTMLButtonElement;
    checkRuntime.disabled = this._busy;
    checkRuntime.addEventListener('click', () => this._checkDemoRuntime());
    actions.appendChild(checkRuntime);
    const liveValidation = el('button', 'xb-pd-browse', {
      textContent: 'Check Live Validation',
      type: 'button',
    }) as HTMLButtonElement;
    liveValidation.disabled = this._busy;
    liveValidation.addEventListener('click', () => this._checkLiveValidation());
    actions.appendChild(liveValidation);
    const stopRuntime = el('button', 'xb-pd-browse', {
      textContent: 'Stop Runtime',
      type: 'button',
    }) as HTMLButtonElement;
    stopRuntime.disabled = this._busy;
    stopRuntime.addEventListener('click', () => this._stopDemoRuntime());
    actions.appendChild(stopRuntime);
    const detect = el('button', 'xb-pd-browse', {
      textContent: 'Detect Engines',
      type: 'button',
    }) as HTMLButtonElement;
    detect.disabled = this._busy;
    detect.addEventListener('click', () => this._detectEngineTools());
    actions.appendChild(detect);
    const smoke = el('button', 'xb-pd-browse', {
      textContent: 'Run Editor-Free Proof',
      type: 'button',
    }) as HTMLButtonElement;
    smoke.disabled = this._busy;
    smoke.addEventListener('click', () => this._runThreeEngineSmoke());
    actions.appendChild(smoke);
    const multiplayer = el('button', 'xb-pd-browse', {
      textContent: 'Run Network Primitives Smoke',
      type: 'button',
    }) as HTMLButtonElement;
    multiplayer.disabled = this._busy;
    multiplayer.addEventListener('click', () => this._runMultiplayerSmoke());
    actions.appendChild(multiplayer);
    form.appendChild(actions);

    if (this._lastDemoStatus) {
      form.appendChild(this._buildDemoStatus(this._lastDemoStatus));
    } else if (this._demoRuntimeStatus) {
      const runtime = el('div', 'xb-pd-demo-list');
      runtime.appendChild(demoItem(
        'Live runtime',
        Boolean(this._demoRuntimeStatus.running),
        demoRuntimeDetail(this._demoRuntimeStatus),
      ));
      this._appendRuntimeConnectionItems(runtime, this._demoRuntimeStatus);
      form.appendChild(runtime);
    } else if (this._engineTools.length > 0) {
      const tools = el('div', 'xb-pd-demo-list');
      for (const tool of this._engineTools) {
        tools.appendChild(demoItem(
          `${tool.label} executable`,
          Boolean(tool.detected),
          tool.detected
            ? `Detected: ${tool.executable_path}`
            : `${tool.reason ?? 'Not detected.'} Paste the executable path above if it is installed.`,
        ));
      }
      form.appendChild(tools);
    } else {
      const steps = el('ol', 'xb-pd-steps');
      for (const step of [
        'Choose the Godot, Unity, and Unreal project folders.',
        'Click Check Demo to see what is ready.',
        'Use Start Session to start runtime and launch every ready engine project.',
        'Use Run Editor-Free Proof to confirm one runtime can feed three clients without opening the engines.',
        'Use Run Network Primitives Smoke to confirm host/client, lockstep, prediction, reconciliation, and desync checks.',
      ]) {
        steps.appendChild(el('li', '', { textContent: step }));
      }
      form.appendChild(steps);
    }
    if (this._lastMultiplayerSmoke) {
      form.appendChild(this._buildMultiplayerSmokeStatus(this._lastMultiplayerSmoke));
    }
    if (this._lastLiveValidation) {
      form.appendChild(this._buildLiveValidationStatus(this._lastLiveValidation));
    }
    return form;
  }

  private _buildDemoStatus(status: ThreeEngineDemoStatus): HTMLElement {
    const wrap = el('div', 'xb-pd-demo-list');
    const proofReady = Boolean(status.editor_free_proof_ready);
    const runtimeStatus = status.runtime_status ?? this._demoRuntimeStatus;
    if (runtimeStatus) {
      wrap.appendChild(demoItem(
        'Live runtime',
        Boolean(runtimeStatus.running),
        demoRuntimeDetail(runtimeStatus),
      ));
      this._appendRuntimeConnectionItems(wrap, runtimeStatus);
    }
    wrap.appendChild(demoItem(
      'Editor-free runtime proof',
      proofReady,
      proofReady
        ? `Ready. Runtime: ${status.runtime_bin ?? ''}`
        : `Not ready. Runtime ready: ${yesNo(status.runtime_ready)}; smoke tool ready: ${yesNo(status.smoke_tool_ready)}; CGS ready: ${yesNo(status.cgs_exists)}.`,
    ));
    for (const engine of status.engines ?? []) {
      wrap.appendChild(this._buildEngineDemoItem(engine));
    }
    const tools = status.engine_tools ?? this._engineTools;
    if (tools.length > 0) {
      for (const tool of tools) {
        wrap.appendChild(demoItem(
          `${tool.label} executable`,
          Boolean(tool.detected || this._demoExecutableFor(tool.engine)),
          tool.detected
            ? `Detected: ${tool.executable_path}`
            : `${tool.reason ?? 'Not detected.'} Paste the executable path above if it is installed.`,
        ));
      }
    }
    const steps = el('ol', 'xb-pd-steps');
    for (const step of status.steps ?? []) {
      steps.appendChild(el('li', '', { textContent: step }));
    }
    wrap.appendChild(steps);
    return wrap;
  }

  private _buildMultiplayerSmokeStatus(smoke: MultiplayerSmokeResult): HTMLElement {
    const wrap = el('div', 'xb-pd-demo-list');
    wrap.appendChild(demoItem(
      'Network primitives smoke',
      Boolean(smoke.ok),
      smoke.ok
        ? 'Passed: host/client lifecycle, lockstep input, prediction/reconciliation, desync detection, and deterministic final digest.'
        : `Failed: ${smoke.error || 'see terminal output for details.'}`,
    ));
    for (const step of smoke.steps ?? []) {
      wrap.appendChild(demoItem(
        step.label ?? step.id ?? 'Smoke step',
        Boolean(step.ok),
        step.detail ?? '',
      ));
    }
    return wrap;
  }

  private _buildLiveValidationStatus(status: LiveValidationStatus): HTMLElement {
    const wrap = el('div', 'xb-pd-demo-list');
    wrap.appendChild(demoItem(
      'Engine live validation',
      Boolean(status.ok),
      liveValidationOverall(status),
    ));
    if (status.unreal_prerequisite && !status.unreal_prerequisite.ok) {
      wrap.appendChild(demoItem(
        'Unreal prerequisite',
        false,
        `${status.unreal_prerequisite.reason ?? 'Unreal prerequisite is missing.'} ${status.unreal_prerequisite.next_step ?? ''}`.trim(),
      ));
    }
    for (const engine of status.engines ?? []) {
      wrap.appendChild(demoItem(
        `${engine.label} live proof`,
        Boolean(engine.ready),
        engine.ready
          ? 'Connected, received runtime snapshots, sent input/feedback, and reported applied state.'
          : engine.next_step ?? 'Open this engine project, press Play, then check again.',
      ));
      for (const step of engine.steps ?? []) {
        wrap.appendChild(demoItem(
          `${engine.label}: ${step.label ?? step.id ?? 'check'}`,
          Boolean(step.ok),
          step.detail ?? '',
        ));
      }
    }
    return wrap;
  }

  private _appendRuntimeConnectionItems(wrap: HTMLElement, runtimeStatus: DemoRuntimeStatus): void {
    const connections = runtimeStatus.engine_connections ?? runtimeConnectionsFromAdapter(runtimeStatus);
    for (const connection of connections) {
      wrap.appendChild(demoItem(
        `${connection.label} live connection`,
        Boolean(connection.connected),
        connection.connected
          ? `Connected to the shared runtime. Tick ${connection.tick ?? runtimeStatus.snapshot_tick ?? runtimeStatus.tick ?? 0}, snapshots sent ${connection.snapshots_sent ?? 0}, input packets ${connection.input_packets_received ?? 0}, feedback messages ${connection.feedback_messages_received ?? 0}, snapshot ${shortHash(connection.snapshot_hash || runtimeStatus.snapshot_hash || runtimeStatus.state_hash || '')}.`
          : `Waiting for ${connection.label}. Open the project and press Play after Start Runtime.`,
      ));
    }
  }

  private _buildEngineDemoItem(engine: DemoEngineStatus): HTMLElement {
    const ready = Boolean(engine.ready && engine.adapter_installed);
    const item = el('div', 'xb-pd-demo-item');
    const top = el('div', 'xb-pd-demo-top');
    top.appendChild(el('div', 'xb-pd-demo-name', { textContent: engine.label }));
    top.appendChild(el('div', `xb-pd-demo-badge ${ready ? 'ok' : 'warn'}`, {
      textContent: ready ? 'Ready' : 'Needs setup',
    }));
    item.appendChild(top);
    item.appendChild(el('div', 'xb-pd-demo-detail', {
      textContent: `${engine.reason ?? ''}${engine.next_step ? ` ${engine.next_step}` : ''}`,
    }));
    const actions = el('div', 'xb-pd-demo-actions');
    const launch = el('button', 'xb-pd-browse', {
      textContent: `Launch ${engine.label}`,
      type: 'button',
    }) as HTMLButtonElement;
    launch.disabled = this._busy || !engine.ready;
    launch.addEventListener('click', () => this._launchDemoEngine(engine.engine));
    actions.appendChild(launch);
    item.appendChild(actions);
    return item;
  }

  private _buildEngineRow(current: EngineType, onSelect: (engine: EngineType) => void): HTMLElement {
    const row = el('div', 'xb-pd-row');
    row.appendChild(el('label', 'xb-pd-label', { textContent: 'Engine' }));
    const engines = el('div', 'xb-pd-engines');
    for (const engine of ENGINE_OPTIONS) {
      const btn = el('button', `xb-pd-engine${current === engine.id ? ' on' : ''}`, {
        textContent: engine.label,
        type: 'button',
      });
      btn.addEventListener('click', () => onSelect(engine.id));
      engines.appendChild(btn);
    }
    row.appendChild(engines);
    return row;
  }

  private _buildTemplateRow(
    current: string,
    engineType: EngineType,
    onChange: (templateId: string) => void,
  ): HTMLElement {
    const row = el('div', 'xb-pd-row');
    row.appendChild(el('label', 'xb-pd-label', { textContent: 'Template' }));
    const select = el('select', 'xb-pd-select') as HTMLSelectElement;
    for (const template of this._templates) {
      const option = document.createElement('option');
      option.value = template.template_id;
      option.textContent = template.label;
      select.appendChild(option);
    }
    if (this._templates.length === 0) {
      const option = document.createElement('option');
      option.value = 'blank_3d';
      option.textContent = 'Blank 3D';
      select.appendChild(option);
    }
    select.value = current;
    select.addEventListener('change', () => onChange(select.value));
    row.appendChild(select);
    row.appendChild(el('div', 'xb-pd-template-meta', {
      textContent: templateMeta(this._templates, current, engineType),
    }));
    return row;
  }

  private _buildInputRow(
    label: string,
    value: string,
    placeholder: string,
    onInput: (value: string) => void,
    browse?: { title: string },
  ): HTMLElement {
    const row = el('div', 'xb-pd-row');
    row.appendChild(el('label', 'xb-pd-label', { textContent: label }));
    const inputWrap = browse ? el('div', 'xb-pd-path-row') : row;
    const input = el('input', 'xb-pd-input') as HTMLInputElement;
    input.type = 'text';
    input.placeholder = placeholder;
    input.value = value;
    input.addEventListener('input', () => onInput(input.value));
    inputWrap.appendChild(input);
    if (browse) {
      const browseBtn = el('button', 'xb-pd-browse', { textContent: 'Browse', type: 'button' });
      browseBtn.addEventListener('click', () => {
        this._pickFolder(browse.title, input.value, picked => {
          input.value = picked;
          onInput(picked);
          this._render();
        });
      });
      inputWrap.appendChild(browseBtn);
      row.appendChild(inputWrap);
    }
    return row;
  }

  private _buildForceRow(value: boolean, onChange: (value: boolean) => void): HTMLElement {
    const forceLabel = el('label', 'xb-pd-check');
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.checked = value;
    input.addEventListener('change', () => onChange(input.checked));
    forceLabel.appendChild(input);
    forceLabel.appendChild(text('Replace starter files if this folder already has XACE project files.'));
    return forceLabel;
  }

  private _buildOverwriteRow(value: boolean, onChange: (value: boolean) => void): HTMLElement {
    const label = el('label', 'xb-pd-check');
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.checked = value;
    input.addEventListener('change', () => onChange(input.checked));
    label.appendChild(input);
    label.appendChild(text('Overwrite existing adapter files in the engine project.'));
    return label;
  }

  private _buildSetMainSceneRow(value: boolean, onChange: (value: boolean) => void): HTMLElement {
    const label = el('label', 'xb-pd-check');
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.checked = value;
    input.addEventListener('change', () => onChange(input.checked));
    label.appendChild(input);
    label.appendChild(text('Set the generated XACE scene as the Godot main scene.'));
    return label;
  }

  private _buildSaveDemoPathsRow(value: boolean, onChange: (value: boolean) => void): HTMLElement {
    const label = el('label', 'xb-pd-check');
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.checked = value;
    input.addEventListener('change', () => onChange(input.checked));
    label.appendChild(input);
    label.appendChild(text('Remember these engine project folders for this XACE project.'));
    return label;
  }

  private async _runPrimaryAction(): Promise<void> {
    if (this._mode === 'health') {
      await this._checkLaunchHealth();
    } else if (this._mode === 'new') {
      await this._createProject();
    } else if (this._mode === 'open') {
      await this._openProject();
    } else if (this._mode === 'import') {
      await this._importEngineProject();
    } else if (this._mode === 'adapter') {
      await this._installAdapterToEngine();
    } else {
      await this._checkThreeEngineDemo();
    }
  }

  private async _checkLaunchHealth(): Promise<void> {
    this._busy = true;
    this._primaryBtn.disabled = true;
    this._setStatus('Refreshing launch health...', '');

    try {
      const [project, certification] = await Promise.all([
        fetchJson<ProjectInfo>('/api/project'),
        fetchJson<CertificationStatusResponse>('/api/project/certify/status'),
      ]);
      this._activeInfo = project;
      if (!certification.ok) {
        throw new Error(certification.error || 'Certification status check failed.');
      }
      this._certificationStatus = certification.certification ?? null;
      const adapterReady = Boolean(project.adapter_status?.healthy || project.adapter_status?.skipped);
      const certReady = Boolean(this._certificationStatus?.ok);
      this._setStatus(`Health refreshed. Adapter ${adapterReady ? 'ready' : 'needs setup'}; certification ${certReady ? 'ready' : 'needs setup'}.`, adapterReady && certReady ? 'ok' : '');
    } catch (error) {
      this._setStatus(readError(error), 'err');
    } finally {
      this._busy = false;
      this._primaryBtn.disabled = this._loading;
      this._render();
    }
  }

  private async _runQuickCertification(): Promise<void> {
    this._busy = true;
    this._primaryBtn.disabled = true;
    this._setStatus('Running quick launch certification...', '');

    try {
      const result = await postJson<CertificationRunResponse>('/api/project/certify/quick', {});
      this._lastCertification = result.certification ?? null;
      this._certificationStatus = result.certification?.status ?? this._certificationStatus;
      if (!result.ok || !result.certification?.ok) {
        throw new Error(result.error || result.certification?.error || 'Quick certification failed.');
      }
      const passed = result.certification.steps?.filter(step => step.ok).length ?? 0;
      const total = result.certification.steps?.length ?? 0;
      this._setStatus(`Quick certification passed. ${passed}/${total} checks ready.`, 'ok');
    } catch (error) {
      this._setStatus(readError(error), 'err');
    } finally {
      this._busy = false;
      this._primaryBtn.disabled = this._loading;
      this._render();
    }
  }

  private async _createProject(): Promise<void> {
    const name = this._newForm.name.trim();
    const projectPath = this._newForm.projectPath.trim();
    if (!name || !projectPath) {
      this._setStatus('Enter both a project name and a project folder.', 'err');
      return;
    }
    const problem = this._projectPathProblem(projectPath, 'create');
    if (problem) {
      this._setStatus(problem, 'err');
      return;
    }
    await this._runProjectRequest('/api/project/create', {
      name,
      project_path: projectPath,
      engine_type: this._newForm.engineType,
      template_id: this._newForm.templateId,
      force: this._newForm.force,
    }, 'Created');
  }

  private async _openProject(): Promise<void> {
    const projectPath = this._openPath.trim();
    if (!projectPath) {
      this._setStatus('Enter a project folder to open.', 'err');
      return;
    }
    const problem = this._projectPathProblem(projectPath, 'open');
    if (problem) {
      this._setStatus(problem, 'err');
      return;
    }
    await this._switchActiveProject(projectPath, 'Opened');
  }

  private async _importEngineProject(): Promise<void> {
    const name = this._importForm.name.trim();
    const engineProjectPath = this._importForm.engineProjectPath.trim();
    const projectPath = this._importForm.xaceProjectPath.trim();
    if (!name || !engineProjectPath || !projectPath) {
      this._setStatus('Enter a project name, engine project folder, and XACE project folder.', 'err');
      return;
    }
    const problem = this._projectPathProblem(projectPath, 'import');
    if (problem) {
      this._setStatus(problem, 'err');
      return;
    }
    await this._runProjectRequest('/api/project/import-engine', {
      name,
      engine_project_path: engineProjectPath,
      project_path: projectPath,
      engine_type: this._importForm.engineType,
      template_id: this._importForm.templateId,
      force: this._importForm.force,
    }, 'Imported');
  }

  private async _runProjectRequest(url: string, payload: unknown, verb: string): Promise<void> {
    this._busy = true;
    this._primaryBtn.disabled = true;
    this._setStatus(`${verb.replace(/ed$/, 'ing')} project...`, '');

    try {
      const result = await postJson<ProjectMutationResponse>(url, payload);
      if (!result.ok) {
        throw new Error(result.error || `${verb} project failed.`);
      }
      this._rememberProject(result);
      this._recent = loadRecentProjects();
      if (result.restart_required && result.project_dir) {
        await this._switchActiveProject(result.project_dir, verb, result.adapter_install);
        return;
      }
      this._activeInfo = await fetchJson<ProjectInfo>('/api/project');
      const name = result.manifest?.name ?? result.project_dir ?? 'Project';
      const path = result.project_dir ?? '';
      const suffix = result.restart_required
        ? ' It is valid. In this dev build, restart Builder with that folder to make it active.'
        : ' It is now the active project.';
      const adapterText = adapterInstallText(result.adapter_install);
      this._setStatus(`${verb} ${name} at ${path}.${suffix}${adapterText}`, 'ok');
      this._render();
    } catch (error) {
      this._setStatus(readError(error), 'err');
    } finally {
      this._busy = false;
      this._primaryBtn.disabled = this._loading;
    }
  }

  private _rememberProject(info: ProjectMutationResponse): void {
    if (!info.project_dir) return;
    saveRecentProject({
      name: info.manifest?.name ?? info.project_dir,
      path: info.project_dir,
      engine: info.manifest?.engine_type ?? '',
      timestamp: Date.now(),
    });
  }

  private _projectPathProblem(projectPath: string, mode: 'create' | 'open' | 'import'): string {
    const normalized = normalizePathForCompare(projectPath);
    if (!normalized) return 'Choose a project folder.';
    if (normalized === '.' || normalized === './' || normalized === '.\\') {
      return 'Choose a game project folder, not the current working folder.';
    }
    const activePath = normalizePathForCompare(this._activeInfo?.project_dir ?? '');
    const activeError = String(this._activeInfo?.error ?? '').toLowerCase();
    if (activePath && normalized === activePath && activeError.includes('source checkout')) {
      return 'Choose a game project folder, not the XACE source checkout.';
    }
    if (mode === 'create' && activePath && normalized === activePath && this._activeInfo?.ok && !this._newForm.force) {
      return 'Choose a new folder, or enable Replace starter files for this existing project.';
    }
    return '';
  }

  private async _switchActiveProject(
    projectPath: string,
    verb: string,
    adapterInstall?: AdapterInstallResult,
  ): Promise<void> {
    this._busy = true;
    this._primaryBtn.disabled = true;
    this._setStatus('Switching project...', '');

    try {
      const result = await postJson<ProjectMutationResponse>('/api/project/switch', {
        project_path: projectPath,
      });
      if (!result.ok) {
        throw new Error(result.error || 'Project switch failed.');
      }
      this._rememberProject(result);
      const name = result.manifest?.name ?? result.project_dir ?? 'Project';
      const adapterText = adapterInstallText(adapterInstall);
      this._setStatus(`${verb} ${name}.${adapterText} Reloading Builder...`, 'ok');
      setTimeout(() => window.location.reload(), 450);
    } catch (error) {
      this._setStatus(readError(error), 'err');
    } finally {
      this._busy = false;
      this._primaryBtn.disabled = this._loading;
    }
  }

  private async _pickFolder(
    title: string,
    initialPath: string,
    onPicked: (path: string) => void,
  ): Promise<void> {
    this._setStatus('Opening folder picker...', '');
    try {
      const result = await postJson<FolderPickResponse>('/api/system/pick-folder', {
        title,
        initial_path: initialPath,
      });
      if (result.ok && result.path) {
        onPicked(result.path);
        this._setStatus('Folder selected.', 'ok');
        return;
      }
      if (result.cancelled) {
        this._setStatus('Folder picker closed.', '');
        return;
      }
      throw new Error(result.error || 'Folder picker is unavailable.');
    } catch (error) {
      this._setStatus(`${readError(error)} You can still type or paste the folder path.`, 'err');
    }
  }

  private async _repairAdapter(): Promise<void> {
    this._busy = true;
    this._primaryBtn.disabled = true;
    this._setStatus('Repairing adapter files...', '');
    this._render();

    try {
      const result = await postJson<AdapterRepairResponse>('/api/project/adapter/reinstall', {});
      if (!result.ok) {
        throw new Error(result.error || result.adapter_install?.error || 'Adapter repair failed.');
      }
      const activeInfo = await fetchJson<ProjectInfo>('/api/project');
      this._activeInfo = activeInfo;
      const statusText = adapterStatusSummary(result.adapter_status, activeInfo.manifest?.engine_type);
      this._setStatus(`Adapter repaired. ${statusText}${adapterInstallText(result.adapter_install)}`, 'ok');
    } catch (error) {
      this._setStatus(readError(error), 'err');
    } finally {
      this._busy = false;
      this._primaryBtn.disabled = this._loading;
      this._render();
    }
  }

  private async _installAdapterToEngine(): Promise<void> {
    const engineProjectPath = this._adapterForm.engineProjectPath.trim();
    if (!engineProjectPath) {
      this._setStatus('Choose the engine project folder first.', 'err');
      return;
    }

    this._busy = true;
    this._primaryBtn.disabled = true;
    this._setStatus('Copying adapter into engine project...', '');

    try {
      const result = await postJson<AdapterEngineInstallResponse>('/api/project/adapter/install-engine', {
        engine_project_path: engineProjectPath,
        overwrite: this._adapterForm.overwrite,
      });
      if (!result.ok || !result.adapter_engine_install?.ok) {
        throw new Error(result.error || result.adapter_engine_install?.error || 'Adapter copy failed.');
      }
      const activeInfo = await fetchJson<ProjectInfo>('/api/project');
      this._activeInfo = activeInfo;
      this._adapterForm.engineProjectPath = activeInfo.adapter_install_plan?.engine_project_path ?? engineProjectPath;
      const install = result.adapter_engine_install;
      const copied = install.copied?.length ?? 0;
      const skipped = install.skipped?.length ?? 0;
      this._setStatus(
        `Copied ${install.label ?? 'engine'} adapter to ${install.destination_path}. ${copied} copied, ${skipped} skipped.`,
        'ok',
      );
    } catch (error) {
      this._setStatus(readError(error), 'err');
    } finally {
      this._busy = false;
      this._primaryBtn.disabled = this._loading;
      this._render();
    }
  }

  private async _setupGodotScene(): Promise<void> {
    const engineProjectPath = this._adapterForm.engineProjectPath.trim();
    if (!engineProjectPath) {
      this._setStatus('Choose the Godot project folder first.', 'err');
      return;
    }

    this._busy = true;
    this._primaryBtn.disabled = true;
    this._setStatus('Setting up Godot scene...', '');

    try {
      const result = await postJson<GodotSceneSetupResponse>('/api/project/adapter/setup-godot-scene', {
        engine_project_path: engineProjectPath,
        overwrite: this._adapterForm.overwrite,
        set_main_scene: this._adapterForm.setMainScene,
      });
      if (!result.ok || !result.godot_scene_setup?.ok) {
        throw new Error(result.error || result.godot_scene_setup?.error || 'Godot scene setup failed.');
      }
      const activeInfo = await fetchJson<ProjectInfo>('/api/project');
      this._activeInfo = activeInfo;
      this._adapterForm.engineProjectPath = activeInfo.adapter_install_plan?.engine_project_path ?? engineProjectPath;
      const setup = result.godot_scene_setup;
      const sceneAction = setup.scene_created
        ? 'Created'
        : setup.scene_skipped
          ? 'Kept existing'
          : 'Prepared';
      const mainText = setup.main_scene_changed ? ' Set it as the main scene.' : '';
      this._setStatus(`${sceneAction} ${setup.scene_resource ?? 'Godot scene'}.${mainText}`, 'ok');
    } catch (error) {
      this._setStatus(readError(error), 'err');
    } finally {
      this._busy = false;
      this._primaryBtn.disabled = this._loading;
      this._render();
    }
  }

  private async _checkThreeEngineDemo(): Promise<void> {
    this._busy = true;
    this._primaryBtn.disabled = true;
    this._setStatus('Checking three-engine demo readiness...', '');

    try {
      const result = await postJson<ThreeEngineDemoResponse>('/api/project/demo/three-engine/status', {
        engine_paths: this._demoEnginePathsPayload(),
        save_paths: this._demoForm.savePaths,
      });
      if (!result.ok || !result.demo?.ok) {
        throw new Error(result.error || 'Demo readiness check failed.');
      }
      this._lastDemoStatus = result.demo;
      this._engineTools = result.demo.engine_tools ?? this._engineTools;
      this._demoRuntimeStatus = result.demo.runtime_status ?? this._demoRuntimeStatus;
      this._setStatus(demoOverallStatus(result.demo), result.demo.editor_free_proof_ready ? 'ok' : '');
    } catch (error) {
      this._setStatus(readError(error), 'err');
    } finally {
      this._busy = false;
      this._primaryBtn.disabled = this._loading;
      this._render();
    }
  }

  private async _runThreeEngineSmoke(): Promise<void> {
    this._busy = true;
    this._primaryBtn.disabled = true;
    this._setStatus('Running editor-free three-client proof...', '');

    try {
      const result = await postJson<ThreeEngineSmokeResponse>('/api/project/demo/three-engine/smoke', {
        engine_paths: this._demoEnginePathsPayload(),
        save_paths: this._demoForm.savePaths,
      });
      if (result.demo) this._lastDemoStatus = result.demo;
      if (result.demo?.engine_tools) this._engineTools = result.demo.engine_tools;
      if (!result.ok || !result.smoke?.ok) {
        throw new Error(result.error || result.smoke?.error || 'Editor-free proof failed.');
      }
      this._demoRuntimeStatus = result.demo?.runtime_status ?? this._demoRuntimeStatus;
      const proof = result.smoke.result;
      this._setStatus(
        `Proof passed. ${proof?.clients ?? 3} clients received tick ${proof?.tick ?? 0}, CGS ${shortHash(proof?.cgs_hash ?? '')}, state ${shortHash(proof?.state_hash ?? '')}.`,
        'ok',
      );
    } catch (error) {
      this._setStatus(readError(error), 'err');
    } finally {
      this._busy = false;
      this._primaryBtn.disabled = this._loading;
      this._render();
    }
  }

  private async _runMultiplayerSmoke(): Promise<void> {
    this._busy = true;
    this._primaryBtn.disabled = true;
    this._setStatus('Running network primitives smoke...', '');

    try {
      const result = await postJson<MultiplayerSmokeResponse>('/api/project/demo/multiplayer/smoke', {});
      if (!result.ok || !result.smoke?.ok) {
        this._lastMultiplayerSmoke = result.smoke ?? null;
        throw new Error(result.error || result.smoke?.error || 'Network primitives smoke failed.');
      }
      this._lastMultiplayerSmoke = result.smoke;
      const passed = result.smoke.steps?.filter(step => step.ok).length ?? 0;
      const total = result.smoke.steps?.length ?? 0;
      this._setStatus(`Network primitives smoke passed. ${passed}/${total} checks ready.`, 'ok');
    } catch (error) {
      this._setStatus(readError(error), 'err');
    } finally {
      this._busy = false;
      this._primaryBtn.disabled = this._loading;
      this._render();
    }
  }

  private async _startDemoRuntime(): Promise<void> {
    this._busy = true;
    this._primaryBtn.disabled = true;
    this._setStatus('Starting one XACE runtime for three engine clients...', '');

    try {
      const result = await postJson<DemoRuntimeResponse>('/api/project/demo/runtime/start', {});
      if (!result.ok || !result.runtime?.ok) {
        throw new Error(result.error || result.runtime?.error || 'Runtime start failed.');
      }
      this._demoRuntimeStatus = result.runtime;
      const running = Boolean(result.runtime.running);
      const detail = running ? runtimeShortStatus(result.runtime) : demoRuntimeDetail(result.runtime);
      this._setStatus(`${running ? 'Runtime ready.' : 'Runtime starting.'} ${detail}`, running ? 'ok' : '');
    } catch (error) {
      this._setStatus(readError(error), 'err');
    } finally {
      this._busy = false;
      this._primaryBtn.disabled = this._loading;
      this._render();
    }
  }

  private async _startDemoSession(): Promise<void> {
    this._busy = true;
    this._primaryBtn.disabled = true;
    this._setStatus('Starting runtime session and launching ready engine projects...', '');

    try {
      const result = await postJson<DemoSessionStartResponse>('/api/project/demo/session/start', {
        engine_paths: this._demoEnginePathsPayload(),
        executable_paths: this._demoExecutablePathsPayload(),
        save_paths: this._demoForm.savePaths,
      });
      if (!result.ok || !result.runtime?.ok) {
        throw new Error(result.error || result.runtime?.error || 'Session start failed.');
      }
      this._demoRuntimeStatus = result.runtime;
      if (result.demo) this._lastDemoStatus = result.demo;
      if (result.engine_tools) this._engineTools = result.engine_tools;
      else if (result.demo?.engine_tools) this._engineTools = result.demo.engine_tools;
      this._fillDetectedExecutables();
      const launched = (result.launches ?? []).filter(item => item.ok).length;
      const skipped = (result.launches ?? []).filter(item => item.skipped).length;
      const failed = (result.launches ?? []).filter(item => !item.ok && !item.skipped).length;
      this._setStatus(
        `Session started. Runtime is ready; ${launched} engine project${launched === 1 ? '' : 's'} launched, ${skipped} skipped, ${failed} failed.`,
        failed > 0 ? '' : 'ok',
      );
    } catch (error) {
      this._setStatus(readError(error), 'err');
    } finally {
      this._busy = false;
      this._primaryBtn.disabled = this._loading;
      this._render();
    }
  }

  private async _checkDemoRuntime(): Promise<void> {
    this._busy = true;
    this._primaryBtn.disabled = true;
    this._setStatus('Checking runtime status...', '');

    try {
      const result = await fetchJson<DemoRuntimeResponse>('/api/project/demo/runtime');
      if (!result.ok) {
        throw new Error(result.error || 'Runtime status check failed.');
      }
      this._demoRuntimeStatus = result.runtime ?? null;
      const running = Boolean(this._demoRuntimeStatus?.running);
      this._setStatus(
        running ? runtimeShortStatus(this._demoRuntimeStatus!) : demoRuntimeDetail(this._demoRuntimeStatus ?? {}),
        running ? 'ok' : '',
      );
    } catch (error) {
      this._setStatus(readError(error), 'err');
    } finally {
      this._busy = false;
      this._primaryBtn.disabled = this._loading;
      this._render();
    }
  }

  private async _checkLiveValidation(): Promise<void> {
    this._busy = true;
    this._primaryBtn.disabled = true;
    this._setStatus('Checking real engine live validation. Unreal may build the adapter the first time...', '');

    try {
      const result = await postJson<LiveValidationResponse>('/api/project/demo/live-validation', {
        engine_paths: this._demoEnginePathsPayload(),
        executable_paths: this._demoExecutablePathsPayload(),
        save_paths: this._demoForm.savePaths,
      });
      if (result.demo) this._lastDemoStatus = result.demo;
      if (result.demo?.engine_tools) this._engineTools = result.demo.engine_tools;
      this._demoRuntimeStatus = result.live_validation?.runtime ?? result.demo?.runtime_status ?? this._demoRuntimeStatus;
      this._lastLiveValidation = result.live_validation ?? null;
      if (!result.ok || !result.live_validation) {
        throw new Error(result.error || 'Live validation check failed.');
      }
      const passed = result.live_validation.passed_count ?? 0;
      const total = result.live_validation.engine_count ?? 3;
      this._setStatus(
        `${passed}/${total} engines have live validation proof. ${result.live_validation.next_step ?? ''}`.trim(),
        result.live_validation.ok ? 'ok' : '',
      );
    } catch (error) {
      this._setStatus(readError(error), 'err');
    } finally {
      this._busy = false;
      this._primaryBtn.disabled = this._loading;
      this._render();
    }
  }

  private async _stopDemoRuntime(): Promise<void> {
    this._busy = true;
    this._primaryBtn.disabled = true;
    this._setStatus('Stopping runtime...', '');

    try {
      const result = await postJson<DemoRuntimeResponse>('/api/project/demo/runtime/stop', {});
      if (!result.ok) {
        throw new Error(result.error || result.runtime?.error || 'Runtime stop failed.');
      }
      this._demoRuntimeStatus = result.runtime ?? null;
      this._setStatus(result.runtime?.reason ?? 'Runtime stopped.', 'ok');
    } catch (error) {
      this._setStatus(readError(error), 'err');
    } finally {
      this._busy = false;
      this._primaryBtn.disabled = this._loading;
      this._render();
    }
  }

  private _demoEnginePathsPayload(): Record<string, string> {
    return {
      godot: this._demoForm.godotPath.trim(),
      unity: this._demoForm.unityPath.trim(),
      unreal: this._demoForm.unrealPath.trim(),
    };
  }

  private _demoExecutablePathsPayload(): Record<string, string> {
    return {
      godot: this._demoExecutableFor('godot'),
      unity: this._demoExecutableFor('unity'),
      unreal: this._demoExecutableFor('unreal'),
    };
  }

  private async _detectEngineTools(): Promise<void> {
    this._busy = true;
    this._primaryBtn.disabled = true;
    this._setStatus('Detecting installed engines...', '');

    try {
      const result = await fetchJson<DemoEngineToolsResponse>('/api/project/demo/engine-tools');
      if (!result.ok) {
        throw new Error(result.error || 'Engine detection failed.');
      }
      this._engineTools = result.engine_tools ?? [];
      this._fillDetectedExecutables();
      const detected = this._engineTools.filter(tool => tool.detected).length;
      this._setStatus(`Engine detection complete: ${detected}/3 executables found.`, detected > 0 ? 'ok' : '');
    } catch (error) {
      this._setStatus(readError(error), 'err');
    } finally {
      this._busy = false;
      this._primaryBtn.disabled = this._loading;
      this._render();
    }
  }

  private async _launchDemoEngine(engine: DemoEngineKey): Promise<void> {
    const projectPath = this._demoProjectPathFor(engine);
    if (!projectPath) {
      this._setStatus(`Choose the ${labelForEngine(engine)} project folder first.`, 'err');
      return;
    }

    this._busy = true;
    this._primaryBtn.disabled = true;
    this._setStatus(`Launching ${labelForEngine(engine)}...`, '');

    try {
      const result = await postJson<DemoLaunchResponse>('/api/project/demo/launch-engine', {
        engine,
        engine_project_path: projectPath,
        executable_path: this._demoExecutableFor(engine),
      });
      if (!result.ok || !result.launch?.ok) {
        throw new Error(result.error || result.launch?.error || `${labelForEngine(engine)} launch failed.`);
      }
      this._setStatus(`Launched ${result.launch.label ?? labelForEngine(engine)} project.`, 'ok');
    } catch (error) {
      this._setStatus(readError(error), 'err');
    } finally {
      this._busy = false;
      this._primaryBtn.disabled = this._loading;
      this._render();
    }
  }

  private _fillDetectedExecutables(): void {
    this._demoForm.godotExe ||= detectedExecutable(this._engineTools, 'godot');
    this._demoForm.unityExe ||= detectedExecutable(this._engineTools, 'unity');
    this._demoForm.unrealExe ||= detectedExecutable(this._engineTools, 'unreal');
  }

  private _demoProjectPathFor(engine: DemoEngineKey): string {
    if (engine === 'godot') return this._demoForm.godotPath.trim();
    if (engine === 'unity') return this._demoForm.unityPath.trim();
    return this._demoForm.unrealPath.trim();
  }

  private _demoExecutableFor(engine: DemoEngineKey): string {
    if (engine === 'godot') return this._demoForm.godotExe.trim() || detectedExecutable(this._engineTools, 'godot');
    if (engine === 'unity') return this._demoForm.unityExe.trim() || detectedExecutable(this._engineTools, 'unity');
    return this._demoForm.unrealExe.trim() || detectedExecutable(this._engineTools, 'unreal');
  }

  private _setStatus(message: string, kind: '' | 'ok' | 'err'): void {
    if (!this._statusEl) return;
    this._statusEl.className = `xb-pd-status${kind ? ` ${kind}` : ''}`;
    this._statusEl.textContent = message;
  }

  private _injectStyles(): void {
    if (document.getElementById('xb-project-dashboard-styles')) return;
    const style = document.createElement('style');
    style.id = 'xb-project-dashboard-styles';
    style.textContent = STYLES;
    document.head.appendChild(style);
  }
}

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  const data = await response.json() as T;
  if (!response.ok) {
    throw new Error(responseError(data) || `Builder could not complete that request (${response.status}).`);
  }
  return data;
}

async function postJson<T>(url: string, payload: unknown): Promise<T> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = await response.json() as T;
  if (!response.ok) {
    throw new Error(responseError(data) || `Builder could not complete that request (${response.status}).`);
  }
  return data;
}

function responseError(data: unknown): string {
  if (typeof data === 'object' && data !== null) {
    const error = (data as { error?: unknown; detail?: unknown }).error
      ?? (data as { detail?: unknown }).detail;
    if (typeof error === 'string' && error.trim()) {
      return error;
    }
  }
  return '';
}

function parseEngine(value: string | undefined): EngineType {
  return ENGINE_OPTIONS.some(engine => engine.id === value) ? value as EngineType : 'godot';
}

function pickTemplateId(templates: TemplateInfo[], preferred: string | undefined): string {
  if (preferred && templates.some(template => template.template_id === preferred)) {
    return preferred;
  }
  return templates[0]?.template_id ?? 'blank_3d';
}

function labelForEngine(value: string | undefined): string {
  const engine = ENGINE_OPTIONS.find(item => item.id === value);
  return engine?.label ?? (value || 'Unknown');
}

function templateLabel(templates: TemplateInfo[], templateId: string | undefined): string {
  if (!templateId) return 'Unknown';
  return templates.find(template => template.template_id === templateId)?.label ?? templateId;
}

function templateMeta(templates: TemplateInfo[], templateId: string, engineType: EngineType): string {
  const selected = templates.find(template => template.template_id === templateId);
  if (!selected) return 'Starter template details will appear here.';
  const recommended = selected.recommended_engines ?? [];
  const engineNote = recommended.includes(engineType)
    ? `${labelForEngine(engineType)} ready`
    : `Best with: ${recommended.map(labelForEngine).join(', ') || 'any engine'}`;
  const playable = selected.playable === false ? 'setup only' : 'playable starter';
  return `${selected.description} ${engineNote}; ${playable}.`;
}

function primaryLabel(mode: ProjectMode): string {
  if (mode === 'health') return 'Check Health';
  if (mode === 'new') return 'Create Project';
  if (mode === 'open') return 'Open Project';
  if (mode === 'import') return 'Wrap/Link Project';
  if (mode === 'adapter') return 'Copy Adapter Package';
  return 'Check Demo';
}

function tabLabel(mode: ProjectMode): string {
  if (mode === 'health') return 'Health';
  if (mode === 'new') return 'New';
  if (mode === 'open') return 'Open';
  if (mode === 'import') return 'Wrap/Link';
  if (mode === 'adapter') return 'Adapter Package';
  return 'Demo';
}

function commandText(command: string[]): string {
  return command.map(part => part.includes(' ') ? `"${part}"` : part).join(' ');
}

function adapterInstallText(result: AdapterInstallResult | undefined): string {
  if (!result) return '';
  if (result.skipped) return ` ${result.reason ?? 'No engine adapter needed.'}`;
  if (!result.ok) return ` Adapter install warning: ${result.error ?? 'adapter files were not installed.'}`;
  const count = result.files?.length ?? 0;
  return ` Installed ${result.label ?? result.target ?? 'engine'} adapter (${count} files).`;
}

function adapterStatusSummary(
  status: AdapterStatusResult | undefined,
  engineType: string | undefined,
): string {
  if (!status) return 'Not checked yet.';
  if (status.skipped) return status.reason ?? 'No adapter needed.';
  const label = status.label ?? labelForEngine(status.target ?? engineType);
  if (!status.ok) return `${label}: ${status.error ?? 'status check failed'}`;
  if (status.healthy) {
    const count = status.file_count ?? status.expected_count ?? 0;
    return `${label} installed (${count} files).`;
  }
  if (!status.installed) return `${label} not installed yet.`;
  const missingCount = status.missing_files?.length ?? 0;
  if (missingCount > 0) return `${label} missing ${missingCount} file${missingCount === 1 ? '' : 's'}.`;
  return `${label} needs repair.`;
}

function engineProjectPlaceholder(engineType: EngineType): string {
  if (engineType === 'godot') return 'C:\\path\\to\\godot-project';
  if (engineType === 'unity') return 'C:\\path\\to\\unity-project';
  if (engineType === 'unreal') return 'C:\\path\\to\\unreal-project';
  return 'C:\\path\\to\\engine-project';
}

function adapterInstallSteps(engineType: EngineType): string[] {
  if (engineType === 'godot') {
    return [
      'Choose the folder that contains project.godot.',
      'XACE copies the Godot adapter into addons/xace.',
      'In Godot, enable Project > Project Settings > Plugins > XACE Adapter.',
      'Use Setup Godot Scene to create scenes/xace_runtime_scene.tscn, or instance XaceAdapter in your own scene.',
    ];
  }
  if (engineType === 'unity') {
    return [
      'Choose the Unity project folder.',
      'XACE copies the Unity adapter package into Assets/XACE.',
      'Return to Unity and let it recompile the scripts.',
      'Use Tools > XACE > Create Runtime Object to add the scene components.',
    ];
  }
  if (engineType === 'unreal') {
    return [
      'Choose the Unreal project folder.',
      'XACE copies the Unreal adapter plugin into Plugins/XACE.',
      'Reopen or rebuild the Unreal project so Unreal discovers the plugin.',
      'Add XACE components to an Actor: Transport, Input Collector, and Delta Applicator.',
    ];
  }
  return ['Headless projects do not need an engine adapter.'];
}

function readDemoEngineProjects(value: unknown): Record<'godot' | 'unity' | 'unreal', string> {
  const source = typeof value === 'object' && value !== null
    ? value as Record<string, unknown>
    : {};
  return {
    godot: typeof source.godot === 'string' ? source.godot : '',
    unity: typeof source.unity === 'string' ? source.unity : '',
    unreal: typeof source.unreal === 'string' ? source.unreal : '',
  };
}

function detectedExecutable(tools: DemoEngineTool[], engine: DemoEngineKey): string {
  return tools.find(tool => tool.engine === engine && tool.detected)?.executable_path ?? '';
}

function demoItem(label: string, ok: boolean, detail: string): HTMLElement {
  const item = el('div', 'xb-pd-demo-item');
  const top = el('div', 'xb-pd-demo-top');
  top.appendChild(el('div', 'xb-pd-demo-name', { textContent: label }));
  top.appendChild(el('div', `xb-pd-demo-badge ${ok ? 'ok' : 'warn'}`, {
    textContent: ok ? 'Ready' : 'Needs setup',
  }));
  item.appendChild(top);
  item.appendChild(el('div', 'xb-pd-demo-detail', { textContent: detail }));
  return item;
}

function demoOverallStatus(status: ThreeEngineDemoStatus): string {
  const ready = status.ready_count ?? 0;
  const installed = status.adapter_installed_count ?? 0;
  const proof = status.editor_free_proof_ready ? 'runtime proof ready' : 'runtime proof needs build/check';
  const runtime = status.runtime_status?.running ? 'live runtime running' : 'live runtime stopped';
  return `Demo check complete: ${ready}/3 engine folders valid, ${installed}/3 adapters installed, ${proof}, ${runtime}.`;
}

function demoRuntimeDetail(status: DemoRuntimeStatus): string {
  if (status.running) {
    return runtimeShortStatus(status);
  }
  const endpoint = status.control_endpoint ? ` Control: ${status.control_endpoint}.` : '';
  const reason = status.reason || status.error || 'Runtime is not running yet.';
  return `${reason}${endpoint}`;
}

function runtimeShortStatus(status: DemoRuntimeStatus): string {
  const endpoint = status.control_endpoint ?? 'control socket';
  const tick = status.snapshot_tick ?? status.tick ?? 0;
  const connectedCount = status.connected_engines?.length
    ?? runtimeConnectionsFromAdapter(status).filter(item => item.connected).length;
  const connected = connectedCount > 0 ? `${connectedCount}/3 engines connected` : 'waiting for engines';
  const proof = status.snapshot_hash ? ` Snapshot ${shortHash(status.snapshot_hash)}.` : '';
  const adapter = status.adapter_type ? ` Adapter: ${status.adapter_type}.` : '';
  const counters = ` Sent ${status.engine_snapshots_sent ?? 0} snapshots, received ${status.engine_input_packets_received ?? 0} input packets and ${status.engine_feedback_messages_received ?? 0} feedback messages.`;
  return `Running at ${endpoint}, tick ${tick}, ${connected}.${proof}${adapter}${counters}`;
}

function liveValidationOverall(status: LiveValidationStatus): string {
  const passed = status.passed_count ?? 0;
  const total = status.engine_count ?? 3;
  const summary = status.summary ?? `${passed}/${total} engines have live adapter proof.`;
  const next = status.ok ? 'All live checks passed.' : (status.next_step ?? 'Open the engines, press Play, and check again.');
  return `${summary} ${next}`;
}

function runtimeConnectionsFromAdapter(status: DemoRuntimeStatus): DemoRuntimeEngineConnection[] {
  const connected = new Set(parseConnectedEngines(status.adapter_type ?? ''));
  return (['godot', 'unity', 'unreal'] as DemoEngineKey[]).map(engine => ({
    engine,
    label: labelForEngine(engine),
    connected: connected.has(engine),
    tick: connected.has(engine) ? (status.snapshot_tick ?? status.tick ?? null) : null,
    snapshot_hash: connected.has(engine) ? (status.snapshot_hash ?? status.state_hash ?? '') : '',
    snapshots_sent: 0,
    input_packets_received: 0,
    feedback_payloads_received: 0,
    feedback_messages_received: 0,
    malformed_messages: 0,
    dropped_inputs: 0,
    queued_inputs: 0,
    queued_feedback: 0,
  }));
}

function parseConnectedEngines(adapterType: string): DemoEngineKey[] {
  let value = adapterType.trim().toLowerCase();
  if (value.startsWith('multi(') && value.endsWith(')')) {
    value = value.slice(6, -1);
  }
  return value
    .split(',')
    .map(item => item.trim())
    .filter((item): item is DemoEngineKey => item === 'godot' || item === 'unity' || item === 'unreal');
}

function yesNo(value: boolean | undefined): string {
  return value ? 'yes' : 'no';
}

function shortHash(value: string): string {
  return value ? value.slice(0, 12) : '-';
}

function readError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function loadRecentProjects(): RecentProject[] {
  try {
    const raw = window.localStorage.getItem(RECENT_KEY);
    const parsed = raw ? JSON.parse(raw) as unknown : [];
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((item): item is RecentProject => (
        typeof item === 'object' &&
        item !== null &&
        typeof (item as RecentProject).path === 'string' &&
        typeof (item as RecentProject).name === 'string'
      ))
      .slice(0, 8);
  } catch {
    return [];
  }
}

function saveRecentProject(project: RecentProject): void {
  const existing = loadRecentProjects().filter(item => item.path !== project.path);
  const next = [project, ...existing].slice(0, 8);
  try {
    window.localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    // Ignore storage failures; recent projects are a convenience only.
  }
}

function suggestNewProjectPath(currentPath: string, projectName: string): string {
  const clean = currentPath.trim();
  if (!clean || clean === './project') return './project';
  const separatorIndex = Math.max(clean.lastIndexOf('\\'), clean.lastIndexOf('/'));
  const parent = separatorIndex >= 0 ? clean.slice(0, separatorIndex) : '';
  const separator = clean.includes('\\') ? '\\' : '/';
  const folder = slugPathSegment(projectName || 'New XACE Project');
  return parent ? `${parent}${separator}${folder}` : folder;
}

function slugPathSegment(value: string): string {
  const cleaned = value
    .trim()
    .replace(/[<>:"/\\|?*]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  return cleaned || 'New XACE Project';
}

function normalizePathForCompare(value: string): string {
  return value.trim().replace(/[\\/]+$/, '').toLowerCase();
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  })[ch] ?? ch);
}

function el(tag: string, cls: string, attrs: Record<string, string> = {}): HTMLElement {
  const element = document.createElement(tag);
  if (cls) element.className = cls;
  for (const [key, value] of Object.entries(attrs)) {
    if (key === 'textContent') element.textContent = value;
    else element.setAttribute(key, value);
  }
  return element;
}

function text(content: string): Text {
  return document.createTextNode(content);
}
