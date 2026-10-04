import re
from pathlib import Path

config_path = Path("/config/.hermes/profiles/matthijs/cache/scratch/stitch_design/stitch_llm_system_eval_console/system_1_flow_pipeline_engine_configuration/code.html")
config_raw = config_path.read_text(encoding="utf-8")

# Extract main body of config page (from <header ...> to </footer> inclusive)
config_match = re.search(r'(<header class="flex justify-between items-center w-full px-space-md h-12.*?</header>.*?<main.*?</main>.*?<footer class="sticky bottom-0.*?</footer\s*>)', config_raw, re.DOTALL)
if not config_match:
    raise RuntimeError("Could not match config page body from code.html")

config_body = config_match.group(1)

# Adapt config body for view switching and escaped characters
config_body = config_body.replace('href="#"', 'href="javascript:void(0)" onclick="switchView(\'eval\')"')
config_body = config_body.replace('Back to Evaluation Console</a>', 'Back to Evaluation Console</button>')
config_body = config_body.replace('<a class="flex items-center gap-1.5 px-2 py-1 rounded hover:bg-surface-container', '<button onclick="switchView(\'eval\')" class="flex items-center gap-1.5 px-2 py-1 rounded hover:bg-surface-container cursor-pointer')
config_body = config_body.replace('<button class="flex items-center gap-1.5 bg-primary hover:bg-primary-container text-on-primary px-3 py-1.5 rounded text-label-code-sm font-label-code-sm font-medium transition-all shadow-sm active:scale-[0.99]"><span class="material-symbols-outlined text-[15px]">bolt</span><span class="">Deploy Policy</span></button>', '<button onclick="savePolicyConfig()" class="flex items-center gap-1.5 bg-primary hover:bg-primary-hover text-on-primary px-3 py-1.5 rounded text-label-code-sm font-label-code-sm font-medium transition-all shadow-sm active:scale-[0.99] cursor-pointer"><span class="material-symbols-outlined text-[15px]">bolt</span><span id="btn-deploy-policy">Deploy Policy</span></button>')
config_body = config_body.replace('<button class="px-4 py-1.5 rounded bg-primary hover:bg-primary-container text-on-primary font-semibold flex items-center gap-2 shadow-sm transition-all active:scale-[0.99]">', '<button onclick="savePolicyConfig()" class="px-4 py-1.5 rounded bg-primary hover:bg-primary-hover text-on-primary font-semibold flex items-center gap-2 shadow-sm transition-all active:scale-[0.99] cursor-pointer">')
config_body = config_body.replace('<button class="px-3 py-1.5 rounded border border-surface-container-highest bg-surface-container-lowest hover:bg-surface-container text-secondary hover:text-on-surface transition-colors font-medium">\n          Discard Changes\n        </button>', '<button onclick="switchView(\'eval\')" class="px-3 py-1.5 rounded border border-surface-container-highest bg-surface-container-lowest hover:bg-surface-container text-secondary hover:text-on-surface transition-colors font-medium cursor-pointer">\n          Return to Trace Console\n        </button>')

# Escape raw backslashes in config body for python multiline string
config_body = config_body.replace('\\x00', '\\\\x00')
config_body = config_body.replace('\\u200B', '\\\\u200B')
config_body = config_body.replace('\\u0308', '\\\\u0308')

target_py = Path("/config/projects/HomeAssistant-Apps/apps/ha-system-1/rootfs/usr/src/app/ui.py")
current_py = target_py.read_text(encoding="utf-8")

# In current_py, replace the simple view-config with config_body inside the container
view_config_replacement = f"""<!-- ========================================================================= -->
<!-- VIEW 2: FLOW PIPELINE & ENGINE CONFIGURATION WORKSTATION                  -->
<!-- ========================================================================= -->
<div id="view-config" class="flex-1 overflow-y-auto bg-surface flex flex-col hidden">
{config_body}
</div>"""

pattern = r'<!-- ========================================================================= -->\s*<!-- VIEW 2: FLOW PIPELINE & ENGINE CONFIGURATION.*?</div>\s*</div>\s*(?=<!-- Subtle Bottom Status Bar -->)'
new_py = re.sub(pattern, view_config_replacement + "\n\n", current_py, flags=re.DOTALL)

# Also ensure gear wheel button exists in header
if 'id="gear-btn"' not in new_py:
    gear_snippet = """    <!-- Gear Wheel Settings Button in Top Right -->
    <button id="gear-btn" onclick="switchView('config')" class="p-1.5 rounded hover:bg-surface-container-low transition-colors duration-150 text-secondary hover:text-primary cursor-pointer border border-transparent hover:border-surface-container-highest" title="System Settings / Flow Pipeline Configuration">
      <span class="material-symbols-outlined text-[20px]">settings</span>
    </button>"""
    new_py = new_py.replace('<button onclick="syncRegistry()"', gear_snippet + '\n    <button onclick="syncRegistry()"')

target_py.write_text(new_py, encoding="utf-8")
print("ui.py successfully assembled, new length:", len(new_py))
