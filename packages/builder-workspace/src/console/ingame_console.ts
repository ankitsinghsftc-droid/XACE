/**
 * ingame_console.ts
 * Re-exports the console command surface from decision_bar.ts.
 * Both components are defined together for cohesion (they share styles
 * and both belong to the console interaction layer), but the manifest
 * lists them as separate files.
 */
export { CommandPalette as IngameConsole } from './decision_bar';
