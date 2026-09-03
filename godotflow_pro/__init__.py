bl_info = {
    "name": "GodotFlow Pro",
    "author": "Lumka",
    "version": (0, 4, 1),
    "blender": (5, 2, 0),
    "location": "View3D > Sidebar (N) > Godot",
    "description": "One-click Godot 4 Pipeline: Auto-Collisions with Auto Decimate, Animation Libraries, Auto Centering Objects, VAT Animations",
    "category": "Import-Export",
    "doc_url": "https://github.com/your-username/godotflow-pro",
    "tracker_url": "https://github.com/your-username/godotflow-pro/issues",
}

import bpy
import os
import re
import json
import time
import math
import platform
import subprocess
import threading
import urllib.request
import gpu
from gpu_extras.batch import batch_for_shader
import blf

# ==============================================================================
# КОНФИГУРАЦИЯ ССЫЛОК И РЕПОЗИТОРИЯ (УКАЖИТЕ ВАШИ ДАННЫЕ)
# ==============================================================================
CURRENT_VERSION = bl_info["0.5.2"]
GITHUB_REPO = "Arseinc8G/godotflow-pro"  # Формат: "владелец/репозиторий"
BOOSTY_URL = "https://boosty.to/mrfock" # Ваша ссылка на Boosty
BLENDER_EXTENSIONS_URL = "https://extensions.blender.org/"

# ==============================================================================
# 1. ASYNC UPDATE CHECKER (GITHUB RELEASES API)
# ==============================================================================

class UpdateChecker:
    """Асинхронный сервис проверки обновлений через GitHub API без подвисания UI."""
    is_checking = False
    has_checked = False
    update_available = False
    latest_version_str = ""
    latest_version_tuple = (0, 0, 0)
    release_url = f"https://github.com/{GITHUB_REPO}/releases"
    error_message = ""

    @classmethod
    def check_for_updates_async(cls, force=False):
        if cls.is_checking:
            return
        if cls.has_checked and not force:
            return

        cls.is_checking = True
        cls.error_message = ""
        thread = threading.Thread(target=cls._worker, daemon=True)
        thread.start()

    @classmethod
    def _worker(cls):
        api_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        req = urllib.request.Request(
            api_url,
            headers={
                "User-Agent": "Blender-GodotFlow-Addon",
                "Accept": "application/vnd.github.v3+json"
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=5.0) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode('utf-8'))
                    tag_name = data.get("tag_name", "").strip().lstrip("vV")
                    cls.release_url = data.get("html_url", cls.release_url)
                    cls.latest_version_str = tag_name

                    parsed_version = cls._parse_version(tag_name)
                    cls.latest_version_tuple = parsed_version

                    if parsed_version > CURRENT_VERSION:
                        cls.update_available = True
                    else:
                        cls.update_available = False
                    cls.has_checked = True
        except Exception as e:
            cls.error_message = str(e)
            cls.has_checked = True
        finally:
            cls.is_checking = False
            # Запрашиваем перерисовку панелей для мгновенного обновления плашки
            for win in bpy.context.window_manager.windows:
                for area in win.screen.areas:
                    if area.type == 'VIEW_3D':
                        area.tag_redraw()

    @classmethod
    def _parse_version(cls, version_str):
        numbers = re.findall(r'\d+', version_str)
        if not numbers:
            return (0, 0, 0)
        while len(numbers) < 3:
            numbers.append('0')
        return tuple(map(int, numbers[:3]))

def delayed_update_check():
    """Запускается через 3 секунды после старта Blender."""
    UpdateChecker.check_for_updates_async()
    return None

# ==============================================================================
# 2. DYNAMIC ISLAND (APPLE SPRING PHYSICS HUD)
# ==============================================================================

class DynamicIslandManager:
    """Менеджер пружинной физики и рендера Dynamic Island в 3D вьюпорте."""
    def __init__(self):
        self.is_active = False
        self.start_time = 0.0
        self.duration = 2.8
        self.title = ""
        self.subtitle = ""
        self.badge = "Godot 4"
        self.morph_progress = 0.0
        self.alpha = 0.0
        self.content_alpha = 0.0

    def trigger(self, title, subtitle, badge="Godot 4"):
        self.title = title
        self.subtitle = subtitle
        self.badge = badge
        self.start_time = time.time()
        
        if not self.is_active:
            self.is_active = True
            bpy.app.timers.register(self._update, first_interval=0.01)

    def _update(self):
        if not self.is_active:
            return None

        elapsed = time.time() - self.start_time
        
        if elapsed >= self.duration:
            self.is_active = False
            self.alpha = 0.0
            self.morph_progress = 0.0
            self.content_alpha = 0.0
            self._redraw_viewports()
            return None

        expand_duration = 0.45
        collapse_duration = 0.35
        time_left = self.duration - elapsed

        if elapsed < expand_duration:
            t = elapsed / expand_duration
            spring = 1.0 - math.exp(-6.0 * t) * math.cos(9.0 * t)
            self.morph_progress = spring
            self.alpha = min(1.0, t * 2.5)
            self.content_alpha = max(0.0, (t - 0.25) / 0.75) if t > 0.25 else 0.0
        elif time_left < collapse_duration:
            t = time_left / collapse_duration
            ease = t * t * t
            self.morph_progress = ease
            self.alpha = ease
            self.content_alpha = ease * ease
        else:
            self.morph_progress = 1.0
            self.alpha = 1.0
            self.content_alpha = 1.0

        self._redraw_viewports()
        return 0.016

    def _redraw_viewports(self):
        for win in bpy.context.window_manager.windows:
            for area in win.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()

island_manager = DynamicIslandManager()

def draw_capsule_polygon(x, y, w, h, radius, color):
    """Рисует сглаженную капсулу через TRIANGLE_FAN геометрию."""
    segments = 12
    verts = []
    indices = []
    radius = min(radius, h * 0.5, w * 0.5)

    corners = [
        (x + w - radius, y + h - radius),
        (x + radius, y + h - radius),
        (x + radius, y + radius),
        (x + w - radius, y + radius)
    ]

    verts.append((x + w * 0.5, y + h * 0.5))

    for i, (cx, cy) in enumerate(corners):
        start_angle = i * (math.pi / 2.0)
        for s in range(segments + 1):
            angle = start_angle + s * (math.pi / (2.0 * segments))
            verts.append((cx + math.cos(angle) * radius, cy + math.sin(angle) * radius))

    for i in range(1, len(verts) - 1):
        indices.append((0, i, i + 1))
    indices.append((0, len(verts) - 1, 1))

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    shader.bind()
    shader.uniform_float("color", color)
    batch = batch_for_shader(shader, 'TRIS', {"pos": verts}, indices=indices)
    batch.draw(shader)

def draw_viewport_dynamic_island():
    if not island_manager.is_active or island_manager.alpha <= 0.005:
        return

    region = bpy.context.region
    if not region:
        return

    scale = bpy.context.preferences.system.ui_scale
    alpha = island_manager.alpha
    content_a = island_manager.content_alpha
    morph = island_manager.morph_progress

    min_w = 70.0 * scale
    min_h = 32.0 * scale
    max_w = 450.0 * scale
    max_h = 56.0 * scale

    curr_w = min_w + (max_w - min_w) * morph
    curr_h = min_h + (max_h - min_h) * max(0.0, min(1.15, morph))
    curr_radius = curr_h * 0.5

    top_offset = 80.0 * scale
    card_x = (region.width - curr_w) * 0.5
    card_y = region.height - top_offset - curr_h

    gpu.state.blend_set('ALPHA')

    # Тень
    shadow_spread = 10.0 * scale
    draw_capsule_polygon(
        card_x - shadow_spread, card_y - shadow_spread * 0.8,
        curr_w + shadow_spread * 2.0, curr_h + shadow_spread * 1.6,
        curr_radius + shadow_spread,
        (0.0, 0.0, 0.0, alpha * 0.42)
    )

    # 1px фаска
    rim = 1.0 * scale
    draw_capsule_polygon(
        card_x - rim, card_y - rim,
        curr_w + rim * 2.0, curr_h + rim * 2.0,
        curr_radius + rim,
        (1.0, 1.0, 1.0, alpha * 0.13)
    )

    # Корпус
    draw_capsule_polygon(
        card_x, card_y, curr_w, curr_h, curr_radius,
        (0.03, 0.03, 0.04, alpha * 0.98)
    )

    # Внутренний контент
    if content_a > 0.05 and curr_w > 200.0 * scale:
        font_id = 0

        # Зеленый индикатор
        led_size = 10.0 * scale
        led_x = card_x + 16.0 * scale
        led_y = card_y + (curr_h - led_size) * 0.5
        
        draw_capsule_polygon(
            led_x - 2.0 * scale, led_y - 2.0 * scale,
            led_size + 4.0 * scale, led_size + 4.0 * scale,
            (led_size + 4.0 * scale) * 0.5,
            (0.15, 0.95, 0.45, content_a * 0.3)
        )
        draw_capsule_polygon(
            led_x, led_y, led_size, led_size, led_size * 0.5,
            (0.2, 1.0, 0.5, content_a * 0.95)
        )

        # Правый бейдж
        badge_w = 78.0 * scale
        badge_h = 22.0 * scale
        badge_x = card_x + curr_w - badge_w - 14.0 * scale
        badge_y = card_y + (curr_h - badge_h) * 0.5

        draw_capsule_polygon(
            badge_x, badge_y, badge_w, badge_h, badge_h * 0.5,
            (0.14, 0.14, 0.18, content_a * 0.85)
        )
        blf.size(font_id, int(10 * scale))
        blf.color(font_id, 0.8, 0.85, 0.95, content_a * 0.9)
        blf.position(font_id, badge_x + 7.0 * scale, badge_y + 6.0 * scale, 0)
        blf.draw(font_id, island_manager.badge)

        # Заголовок и статус
        text_left = led_x + led_size + 14.0 * scale
        blf.size(font_id, int(13 * scale))
        blf.color(font_id, 1.0, 1.0, 1.0, content_a * 0.98)
        blf.position(font_id, text_left, card_y + curr_h - 22.0 * scale, 0)
        blf.draw(font_id, island_manager.title)

        blf.size(font_id, int(10.5 * scale))
        blf.color(font_id, 0.6, 0.63, 0.68, content_a * 0.88)
        blf.position(font_id, text_left, card_y + 12.0 * scale, 0)
        blf.draw(font_id, island_manager.subtitle)

    gpu.state.blend_set('NONE')

# ==============================================================================
# 3. МЕНЕДЖЕР ПРОЕКТОВ (JSON)
# ==============================================================================

CONFIG_FILENAME = "godotflow_projects_v2.json"
_PROJECTS_CACHE = []

def get_config_path():
    cfg_dir = bpy.utils.user_resource('CONFIG')
    os.makedirs(cfg_dir, exist_ok=True)
    return os.path.join(cfg_dir, CONFIG_FILENAME)

def load_projects_data():
    path = get_config_path()
    default_data = {
        "active_id": "proj_default",
        "projects": {
            "proj_default": {
                "name": "Main Godot Project",
                "path": ""
            }
        }
    }
    if not os.path.exists(path):
        save_projects_data(default_data)
        return default_data
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "projects" not in data or not data["projects"]:
                return default_data
            return data
    except Exception:
        return default_data

def save_projects_data(data):
    try:
        with open(get_config_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"[GodotFlow] Error saving config: {e}")

def get_unique_project_name(desired_name, ignore_id=None):
    data = load_projects_data()
    projects = data.get("projects", {})
    existing = [p["name"].strip().lower() for p_id, p in projects.items() if p_id != ignore_id]
    base = desired_name.strip() or "New Project"
    if base.lower() not in existing:
        return base
    counter = 1
    while f"{base} ({counter})".lower() in existing:
        counter += 1
    return f"{base} ({counter})"

def get_active_project_info():
    data = load_projects_data()
    active_id = data.get("active_id", "")
    projects = data.get("projects", {})
    if active_id in projects:
        return active_id, projects[active_id]
    elif projects:
        first_id = next(iter(projects))
        return first_id, projects[first_id]
    return "NONE", {"name": "No Project", "path": ""}

def get_projects_enum(self, context):
    global _PROJECTS_CACHE
    data = load_projects_data()
    items = []
    for p_id, p_data in data.get("projects", {}).items():
        name = p_data.get("name", "Untitled")
        path = p_data.get("path", "")
        desc = f"Path: {path}" if path else "Path not set"
        items.append((str(p_id), str(name), str(desc)))
    if not items:
        items.append(("NONE", "No Projects (Click Settings)", ""))
    _PROJECTS_CACHE = items
    return _PROJECTS_CACHE

def on_project_changed(self, context):
    data = load_projects_data()
    selected_id = self.godot_project_select
    if selected_id in data.get("projects", {}):
        data["active_id"] = selected_id
        save_projects_data(data)

# ==============================================================================
# 4. ДВИЖОК ЭКСПОРТА В GODOT 4
# ==============================================================================

def open_folder_in_os(path):
    if not path or not os.path.exists(path):
        return False
    sys_name = platform.system()
    try:
        if sys_name == "Windows":
            os.startfile(os.path.abspath(path))
        elif sys_name == "Darwin":
            subprocess.Popen(["open", os.path.abspath(path)])
        else:
            subprocess.Popen(["xdg-open", os.path.abspath(path)])
        return True
    except Exception:
        return False

def get_collection_path(obj):
    if not obj or not obj.users_collection:
        return ""
    coll = obj.users_collection[0]
    parents = []
    curr = coll
    while curr and curr.name != "Scene Collection":
        parents.append(curr.name)
        parent_found = None
        for c in bpy.data.collections:
            if curr.name in c.children:
                parent_found = c
                break
        curr = parent_found
    parents.reverse()
    return os.path.join(*parents) if parents else ""

def calculate_export_directory(context, obj=None):
    scene = context.scene
    _, project = get_active_project_info()
    raw_root = project.get("path", "")
    if not raw_root:
        return ""
    
    root = bpy.path.abspath(raw_root)
    mode = scene.godot_folder_structure
    subpath = ""
    blend_name = "Untitled"
    if bpy.data.is_saved and bpy.data.filepath:
        blend_name = os.path.splitext(os.path.basename(bpy.data.filepath))[0]

    if mode == 'COLLECTION':
        subpath = get_collection_path(obj)
    elif mode == 'FLAT':
        subpath = ""
    elif mode == 'BLEND':
        subpath = blend_name
    elif mode == 'BLEND_AND_COLL':
        coll = get_collection_path(obj)
        subpath = os.path.join(blend_name, coll) if coll else blend_name

    subpath = os.path.normpath(subpath.strip("/\\")) if subpath else ""
    return os.path.join(root, subpath) if subpath and subpath != "." else root

def patch_godot_import_as_anim_library(glb_path):
    import_path = glb_path + ".import"
    if not os.path.exists(import_path):
        content = (
            "[remap]\n\n"
            'importer="animation_library"\n'
            "importer_version=1\n"
            'type="AnimationLibrary"\n\n'
            "[params]\n\n"
            '_custom_type_script=""\n'
        )
        try:
            with open(import_path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception:
            pass
        return

    try:
        with open(import_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        new_lines = []
        for line in lines:
            if line.strip().startswith('importer='):
                new_lines.append('importer="animation_library"\n')
            elif line.strip().startswith('type='):
                new_lines.append('type="AnimationLibrary"\n')
            else:
                new_lines.append(line)
        with open(import_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
    except Exception:
        pass

def get_action_fcurves(action):
    if not action:
        return []
    if hasattr(action, "all_fcurves"):
        try:
            return list(action.all_fcurves)
        except Exception:
            pass
    if hasattr(action, "fcurves") and action.fcurves is not None:
        try:
            return list(action.fcurves)
        except Exception:
            pass
    fcurves = []
    if hasattr(action, "layers"):
        for layer in getattr(action, "layers", []):
            for strip in getattr(layer, "strips", []):
                for channelbag in getattr(strip, "channelbags", []):
                    fcurves.extend(getattr(channelbag, "fcurves", []))
    return fcurves

def action_belongs_to_armature(action, armature):
    if not armature or not armature.data:
        return False
    if action.name.strip().lower() in ("action", "action.001", "action.002", "armatureaction"):
        return False

    fcurves = get_action_fcurves(action)
    if not fcurves:
        return False
    bone_names = {b.name for b in armature.data.bones}
    for fc in fcurves:
        data_path = getattr(fc, "data_path", "")
        match = re.search(r'bones\[["\'](.*?)["\']\]', data_path)
        if match and match.group(1) in bone_names:
            return True
    return False

def clean_action_name(act_name, root_name):
    name = act_name
    prefixes = [f"{root_name}.", f"{root_name}_", f"{root_name}|", "armature.", "armature_", "armature|", "rig.", "rig_", "rig|"]
    for p in prefixes:
        if name.lower().startswith(p.lower()):
            name = name[len(p):]
    name = re.sub(r'^\d+\.', '', name)
    name = re.sub(r'\.\d+$', '', name)
    return name.strip("._- ")

def is_loop_animation(name):
    low = name.lower()
    keys = ["loop", "cycle", "idle", "walk", "run", "swim", "fly", "spin"]
    return any(k in low for k in keys) and not (low.endswith("-loop") or low.endswith("-cycle"))

def export_single_action(context, root_name, armature, meshes, act, target_dir):
    scene = context.scene
    anim_data = armature.animation_data
    if not anim_data:
        anim_data = armature.animation_data_create()

    saved_action = anim_data.action
    orig_name = act.name

    clean_name = clean_action_name(act.name, root_name)
    if scene.godot_auto_loop and is_loop_animation(clean_name):
        clean_name = f"{clean_name}-loop"

    anim_filename = f"{root_name}@{clean_name}.glb"
    anim_path = os.path.join(target_dir, anim_filename)

    try:
        act.name = clean_name
        anim_data.action = act

        bpy.ops.object.select_all(action='DESELECT')
        armature.select_set(True)
        for m in meshes:
            m.select_set(True)
        context.view_layer.objects.active = armature

        kwargs = {
            "filepath": anim_path,
            "use_selection": True,
            "export_format": 'GLB',
            "export_apply": False,
            "export_materials": 'NONE',
            "export_morph": True,
            "export_animations": True,
            "export_def_bones": scene.godot_clean_bones,
            "export_rest_position_armature": False,
            "export_extras": False
        }

        try:
            bpy.ops.export_scene.gltf(**kwargs, export_animation_mode='ACTIVE_ACTIONS')
        except TypeError:
            try:
                bpy.ops.export_scene.gltf(**kwargs, export_all_actions=False, export_nla_strips=False)
            except TypeError:
                bpy.ops.export_scene.gltf(**kwargs)

    finally:
        act.name = orig_name
        anim_data.action = saved_action

    patch_godot_import_as_anim_library(anim_path)

def process_export(context, selected_only=True):
    scene = context.scene
    filter_suffixes = ("-convcol", "-col", "-colonly", "-convcolonly")

    if selected_only:
        objs = [o for o in context.selected_objects if not o.name.endswith(filter_suffixes)]
    else:
        objs = [o for o in scene.objects if o.visible_get() and not o.name.endswith(filter_suffixes)]

    if not objs:
        return 0, 0, "Select objects to export!"

    processed_roots = set()
    export_entries = []

    for obj in objs:
        if obj.type == 'ARMATURE':
            root = obj
            arm = obj
        else:
            arm = obj.find_armature()
            root = arm if arm else obj

        if root not in processed_roots:
            processed_roots.add(root)
            export_entries.append((root, arm))

    mesh_count = 0
    anim_count = 0

    saved_sel = list(context.selected_objects)
    saved_active = context.view_layer.objects.active

    suffix_map = {'CONVEX': "-convcolonly", 'TRIMESH': "-colonly"}
    col_suffix = suffix_map.get(scene.godot_collision_type, "-convcolonly")

    try:
        for root_obj, armature in export_entries:
            target_dir = calculate_export_directory(context, root_obj)
            if not target_dir:
                return 0, 0, "Target directory not configured!"

            os.makedirs(target_dir, exist_ok=True)

            export_name = root_obj.name
            if export_name.lower().startswith(("armature", "armature.")):
                if root_obj.users_collection:
                    export_name = root_obj.users_collection[0].name
                elif root_obj.children:
                    export_name = root_obj.children[0].name

            clean_name = re.sub(r'\.\d+$', '', export_name).strip()
            base_file_path = os.path.join(target_dir, f"{clean_name}.glb")

            meshes = []
            if root_obj.type == 'MESH':
                meshes.append(root_obj)
            for child in root_obj.children_recursive:
                if child.type == 'MESH' and not child.name.endswith(filter_suffixes):
                    meshes.append(child)

            bpy.ops.object.select_all(action='DESELECT')
            root_obj.select_set(True)
            for m in meshes:
                m.select_set(True)
            context.view_layer.objects.active = root_obj

            temp_cols = []
            if scene.godot_make_collisions and not armature:
                for m in meshes:
                    col_mesh = m.data.copy()
                    col_obj = bpy.data.objects.new(f"{m.name}{col_suffix}", col_mesh)
                    context.collection.objects.link(col_obj)
                    col_obj.matrix_world = m.matrix_world.copy()
                    if m.parent:
                        col_obj.parent = m.parent
                        col_obj.matrix_parent_inverse = m.matrix_parent_inverse.copy()

                    if scene.godot_simplify_collision and scene.godot_collision_decimate_ratio < 0.999:
                        mod = col_obj.modifiers.new(name="GodotColDecimate", type='DECIMATE')
                        mod.decimate_type = 'COLLAPSE'
                        mod.ratio = scene.godot_collision_decimate_ratio

                        depsgraph = context.evaluated_depsgraph_get()
                        eval_obj = col_obj.evaluated_get(depsgraph)
                        new_mesh = bpy.data.meshes.new_from_object(eval_obj)

                        col_obj.modifiers.remove(mod)
                        old_mesh = col_obj.data
                        col_obj.data = new_mesh
                        bpy.data.meshes.remove(old_mesh, do_unlink=True)

                    col_obj.select_set(True)
                    temp_cols.append(col_obj)

            orig_matrix = root_obj.matrix_world.copy()
            if scene.godot_center_mesh:
                root_obj.matrix_world.translation = (0, 0, 0)
                context.view_layer.update()

            is_skinned = armature is not None
            export_base_anims = (scene.godot_export_anims and not scene.godot_split_actions) if is_skinned else False

            try:
                bpy.ops.export_scene.gltf(
                    filepath=base_file_path,
                    use_selection=True,
                    export_format='GLB',
                    export_apply=not is_skinned,
                    export_morph=True,
                    export_animations=export_base_anims,
                    export_def_bones=scene.godot_clean_bones,
                    export_rest_position_armature=True,
                    export_extras=True
                )

                if is_skinned and scene.godot_export_anims and scene.godot_split_actions:
                    valid_actions = [a for a in bpy.data.actions if action_belongs_to_armature(a, armature)]
                    for act in valid_actions:
                        export_single_action(context, clean_name, armature, meshes, act, target_dir)
                        anim_count += 1

            finally:
                if scene.godot_center_mesh:
                    root_obj.matrix_world = orig_matrix
                    context.view_layer.update()

                for col_obj in temp_cols:
                    m_data = col_obj.data
                    bpy.data.objects.remove(col_obj, do_unlink=True)
                    bpy.data.meshes.remove(m_data, do_unlink=True)

            mesh_count += 1

    finally:
        bpy.ops.object.select_all(action='DESELECT')
        for o in saved_sel:
            try:
                o.select_set(True)
            except Exception:
                pass
        if saved_active:
            try:
                context.view_layer.objects.active = saved_active
            except Exception:
                pass

    return mesh_count, anim_count, None

# ==============================================================================
# 5. ОПЕРАТОРЫ И ССЫЛКИ
# ==============================================================================

class GODOT_OT_open_url(bpy.types.Operator):
    """Открывает заданный веб-адрес в браузере по умолчанию."""
    bl_idname = "godot_pipeline.open_url"
    bl_label = "Open URL"
    bl_description = "Open external link in browser"

    url: bpy.props.StringProperty()

    def execute(self, context):
        if self.url:
            bpy.ops.wm.url_open(url=self.url)
        return {'FINISHED'}

class GODOT_OT_check_updates_manual(bpy.types.Operator):
    """Принудительно проверяет наличие обновлений на GitHub."""
    bl_idname = "godot_pipeline.check_updates"
    bl_label = "Check for Updates"
    bl_description = "Check GitHub for the latest release"

    def execute(self, context):
        UpdateChecker.check_for_updates_async(force=True)
        self.report({'INFO'}, "Checking for updates in background...")
        return {'FINISHED'}

class GODOT_OT_manage_projects(bpy.types.Operator):
    bl_idname = "godot_pipeline.manage_projects"
    bl_label = "Godot Project Settings"
    bl_description = "Create, edit destination paths, or remove project configurations"

    action: bpy.props.EnumProperty(
        items=[
            ('EDIT', "Edit", "Update target directory for the active project"),
            ('ADD', "New", "Add a new Godot project preset"),
            ('REMOVE', "Delete", "Remove current project preset")
        ],
        default='EDIT'
    )
    new_name: bpy.props.StringProperty(name="Name", default="My Godot Project")
    project_path: bpy.props.StringProperty(name="Target Folder (res://)", subtype='DIR_PATH')

    def invoke(self, context, event):
        active_id, proj = get_active_project_info()
        self.project_path = proj.get("path", "")
        self.new_name = proj.get("name", "My Godot Project")
        return context.window_manager.invoke_props_dialog(self, width=400)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "action", expand=True)
        layout.separator(factor=1.2)
        active_id, proj = get_active_project_info()
        
        box = layout.box()
        col = box.column(align=True)
        if self.action == 'ADD':
            col.prop(self, "new_name", text="Project Name")
            col.prop(self, "project_path", text="Directory")
        elif self.action == 'EDIT':
            col.label(text=f"Project: {proj.get('name')}", icon='PREFERENCES')
            col.prop(self, "new_name", text="Name")
            col.prop(self, "project_path", text="Directory")
        elif self.action == 'REMOVE':
            col.label(text=f"Delete '{proj.get('name')}'?", icon='TRASH')

    def execute(self, context):
        data = load_projects_data()
        active_id, proj = get_active_project_info()

        if self.action == 'ADD':
            unique_name = get_unique_project_name(self.new_name)
            new_id = f"proj_{int(time.time() * 1000)}"
            data["projects"][new_id] = {"name": unique_name, "path": self.project_path}
            data["active_id"] = new_id
            save_projects_data(data)
            context.scene.godot_project_select = new_id
            self.report({'INFO'}, f"Project '{unique_name}' created successfully!")

        elif self.action == 'EDIT':
            if active_id in data.get("projects", {}):
                unique_name = get_unique_project_name(self.new_name, ignore_id=active_id)
                data["projects"][active_id]["name"] = unique_name
                data["projects"][active_id]["path"] = self.project_path
                save_projects_data(data)
                self.report({'INFO'}, f"Project '{unique_name}' updated!")

        elif self.action == 'REMOVE':
            if active_id in data.get("projects", {}):
                del data["projects"][active_id]
                data["active_id"] = next(iter(data["projects"])) if data["projects"] else "NONE"
                save_projects_data(data)
                if data["active_id"] != "NONE":
                    context.scene.godot_project_select = data["active_id"]
                self.report({'INFO'}, "Project deleted.")

        return {'FINISHED'}

class GODOT_OT_open_folder(bpy.types.Operator):
    bl_idname = "godot_pipeline.open_folder"
    bl_label = "Open Target Folder"
    bl_description = "Open the target export folder in system file manager"

    def execute(self, context):
        path = calculate_export_directory(context)
        if not path:
            self.report({'ERROR'}, "Configure a project path in settings first!")
            return {'CANCELLED'}
        os.makedirs(path, exist_ok=True)
        open_folder_in_os(path)
        return {'FINISHED'}

class OBJECT_OT_godot_export_selected_quick(bpy.types.Operator):
    bl_idname = "object.godot_export_selected_quick"
    bl_label = "Export Selected"
    bl_description = "Export only currently selected objects"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        m, a, err = process_export(context, selected_only=True)
        if err:
            self.report({'ERROR'}, err)
            return {'CANCELLED'}
        
        island_manager.trigger(
            "Export Finished",
            f"Sent {m} meshes, {a} anims to Godot",
            badge="Selected"
        )
        self.report({'INFO'}, f"Exported: {m} meshes, {a} animations")
        return {'FINISHED'}

class OBJECT_OT_godot_export_all_quick(bpy.types.Operator):
    bl_idname = "object.godot_export_all_quick"
    bl_label = "Sync Scene"
    bl_description = "Export all visible scene objects to Godot"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        m, a, err = process_export(context, selected_only=False)
        if err:
            self.report({'ERROR'}, err)
            return {'CANCELLED'}
        
        island_manager.trigger(
            "Scene Synced",
            f"Synced {m} meshes, {a} anims",
            badge="Full Sync"
        )
        self.report({'INFO'}, f"Full scene ({m} meshes, {a} anims) synced to Godot")
        return {'FINISHED'}

# ==============================================================================
# 6. UI ПАНЕЛЬ С БАННЕРОМ ОБНОВЛЕНИЙ И ССЫЛКОЙ НА BOOSTY
# ==============================================================================

class VIEW3D_PT_godot_friendly_panel(bpy.types.Panel):
    """Премиальная боковая панель с динамическим баннером обновлений и карточкой автора."""
    bl_label = "GodotFlow Pro"
    bl_idname = "VIEW3D_PT_godot_friendly_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Godot'

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # ======================================================================
        # БАННЕР ОБНОВЛЕНИЙ (ЕСЛИ ЕСТЬ НОВАЯ ВЕРСИЯ НА GITHUB)
        # ======================================================================
        if UpdateChecker.update_available:
            box_update = layout.box()
            col_u = box_update.column(align=True)
            col_u.alert = True
            
            row_up_header = col_u.row(align=True)
            row_up_header.label(text=f"Update Available: v{UpdateChecker.latest_version_str}", icon='IMPORT')
            
            row_up_btn = col_u.row(align=True)
            row_up_btn.scale_y = 1.2
            op = row_up_btn.operator("godot_pipeline.open_url", text="Download Release", icon='URL')
            op.url = UpdateChecker.release_url
            
            layout.separator(factor=0.6)

        # ======================================================================
        # КАРТОЧКА 1: ПРОЕКТ И СТРУКТУРА ПАПКИ
        # ======================================================================
        box_proj = layout.box()
        col_proj = box_proj.column(align=True)
        
        row_header = col_proj.row(align=True)
        row_header.scale_y = 1.15
        row_header.prop(scene, "godot_project_select", text="")
        row_header.operator("godot_pipeline.manage_projects", text="", icon='PREFERENCES')

        col_proj.separator(factor=0.6)
        col_proj.label(text="Folder Hierarchy:", icon='FILE_FOLDER')
        
        row_seg = col_proj.row(align=True)
        row_seg.scale_y = 1.25
        row_seg.prop(scene, "godot_folder_structure", expand=True)

        col_proj.separator(factor=0.7)

        box_path_group = col_proj.box()
        col_path_inner = box_path_group.column(align=True)
        
        target_path = calculate_export_directory(context)
        path_exists = os.path.exists(target_path) if target_path else False

        row_path_status = col_path_inner.row(align=True)
        row_path_status.scale_y = 1.1
        if target_path:
            short_p = target_path if len(target_path) < 32 else "..." + target_path[-28:]
            status_icon = 'CHECKMARK' if path_exists else 'ERROR'
            row_path_status.label(text=short_p, icon=status_icon)
        else:
            row_path_status.label(text="Target path not configured", icon='INFO')

        col_path_inner.separator(factor=0.3)
        row_open = col_path_inner.row(align=True)
        row_open.scale_y = 1.15
        row_open.operator("godot_pipeline.open_folder", text="Open in File Explorer", icon='FOLDER_REDIRECT')

        layout.separator(factor=0.5)

        # ======================================================================
        # КАРТОЧКА 2: ГЕОМЕТРИЯ И КОЛЛИЗИИ
        # ======================================================================
        box_phys = layout.box()
        col_phys = box_phys.column(align=True)
        col_phys.label(text="Geometry & Collisions:", icon='MESH_CUBE')
        col_phys.separator(factor=0.4)

        col_phys_toggles = col_phys.column(align=True)
        col_phys_toggles.scale_y = 1.2
        
        col_phys_toggles.prop(
            scene, "godot_make_collisions", 
            text="Generate Collisions" if scene.godot_make_collisions else "Mesh Only (No Collisions)",
            toggle=True, 
            icon='PHYSICS' if scene.godot_make_collisions else 'SHADING_WIRE'
        )

        col_phys_toggles.prop(
            scene, "godot_center_mesh", 
            text="Center to Origin (0,0,0)" if scene.godot_center_mesh else "Keep World Transform",
            toggle=True, 
            icon='PIVOT_CURSOR'
        )

        if scene.godot_make_collisions:
            col_phys.separator(factor=0.4)
            sub_box = col_phys.box()
            sub_col = sub_box.column(align=True)
            
            sub_col.label(text="Collision Body Shape:")
            row_col_type = sub_col.row(align=True)
            row_col_type.scale_y = 1.05
            row_col_type.prop(scene, "godot_collision_type", expand=True)

            sub_col.separator(factor=0.5)
            
            row_decimate = sub_col.row(align=True)
            row_decimate.scale_y = 1.15
            row_decimate.prop(
                scene, "godot_simplify_collision", 
                text="Optimize Mesh (Decimate)", 
                toggle=True, 
                icon='MOD_DECIM'
            )

            if scene.godot_simplify_collision:
                sub_col.separator(factor=0.3)
                row_ratio = sub_col.row(align=True)
                row_ratio.scale_y = 1.1
                ratio_pct = int(scene.godot_collision_decimate_ratio * 100)
                row_ratio.prop(scene, "godot_collision_decimate_ratio", slider=True, text=f"Density: {ratio_pct}%")

        layout.separator(factor=0.5)

        # ======================================================================
        # КАРТОЧКА 3: СКЕЛЕТ И АНИМАЦИИ
        # ======================================================================
        box_anim = layout.box()
        col_anim = box_anim.column(align=True)
        col_anim.label(text="Armature & Animations:", icon='ARMATURE_DATA')
        col_anim.separator(factor=0.4)

        row_main_anim = col_anim.row(align=True)
        row_main_anim.scale_y = 1.2
        row_main_anim.prop(
            scene, "godot_export_anims", 
            text="Export Animations" if scene.godot_export_anims else "No Animations",
            toggle=True, 
            icon='ACTION' if scene.godot_export_anims else 'ACTION_TWEAK'
        )

        if scene.godot_export_anims:
            col_anim.separator(factor=0.4)
            sub_anim = col_anim.box()
            sub_anim_col = sub_anim.column(align=True)
            sub_anim_col.scale_y = 1.15

            sub_anim_col.prop(
                scene, "godot_split_actions", 
                text="Split Files (Mesh@Walk.glb)", 
                toggle=True, 
                icon='DUPLICATE'
            )
            sub_anim_col.prop(
                scene, "godot_auto_loop", 
                text="Auto-Loop Suffix (-loop)", 
                toggle=True, 
                icon='FILE_REFRESH'
            )
            sub_anim_col.prop(
                scene, "godot_clean_bones", 
                text="Deform Bones Only (No IK)", 
                toggle=True, 
                icon='BONE_DATA'
            )

        layout.separator(factor=0.8)

        # ======================================================================
        # КНОПКИ ДЕЙСТВИЯ (HERO BUTTONS)
        # ======================================================================
        row_actions = layout.row(align=True)
        row_actions.scale_y = 2.2

        row_actions.operator(
            "object.godot_export_selected_quick", 
            text="📦 Selected", 
            icon='RESTRICT_SELECT_OFF'
        )

        row_actions.operator(
            "object.godot_export_all_quick", 
            text="🚀 Sync All", 
            icon='EXPORT'
        )

        layout.separator(factor=0.8)

        # ======================================================================
        # КАРТОЧКА 4: СООБЩЕСТВО, BOOSTY И СТАТУС ВЕРСИИ
        # ======================================================================
        box_footer = layout.box()
        col_footer = box_footer.column(align=True)
        
        # Информационная строка версии + ручная кнопка проверки
        row_ver = col_footer.row(align=True)
        ver_str = f"v{CURRENT_VERSION[0]}.{CURRENT_VERSION[1]}.{CURRENT_VERSION[2]}"
        
        if UpdateChecker.is_checking:
            row_ver.label(text=f"GodotFlow {ver_str} (Checking...)", icon='FILE_REFRESH')
        elif UpdateChecker.update_available:
            row_ver.label(text=f"New: v{UpdateChecker.latest_version_str}", icon='ERROR')
        else:
            row_ver.label(text=f"GodotFlow {ver_str} (Latest)", icon='CHECKMARK')

        row_ver.operator("godot_pipeline.check_updates", text="", icon='FILE_REFRESH')

        col_footer.separator(factor=0.5)

        # Кнопки Boosty и GitHub
        row_links = col_footer.row(align=True)
        row_links.scale_y = 1.15
        
        # Кнопка Boosty
        op_boosty = row_links.operator("godot_pipeline.open_url", text="Support on Boosty", icon='FUND')
        op_boosty.url = BOOSTY_URL
        
        # Кнопка GitHub / Extensions
        op_gh = row_links.operator("godot_pipeline.open_url", text="GitHub", icon='COMMUNITY')
        op_gh.url = f"https://github.com/{GITHUB_REPO}"

# ==============================================================================
# 7. РЕГИСТРАЦИЯ
# ==============================================================================

classes = (
    GODOT_OT_open_url,
    GODOT_OT_check_updates_manual,
    GODOT_OT_manage_projects,
    GODOT_OT_open_folder,
    OBJECT_OT_godot_export_selected_quick,
    OBJECT_OT_godot_export_all_quick,
    VIEW3D_PT_godot_friendly_panel,
)

_draw_handle_3d = None

def register():
    global _draw_handle_3d
    for cls in classes:
        bpy.utils.register_class(cls)

    if _draw_handle_3d is None:
        _draw_handle_3d = bpy.types.SpaceView3D.draw_handler_add(
            draw_viewport_dynamic_island, (), 'WINDOW', 'POST_PIXEL'
        )

    bpy.types.Scene.godot_project_select = bpy.props.EnumProperty(
        name="Project",
        items=get_projects_enum,
        update=on_project_changed,
        description="Select active Godot target project"
    )

    bpy.types.Scene.godot_folder_structure = bpy.props.EnumProperty(
        name="Folder Structure",
        items=[
            ('COLLECTION', "Collections", "By Collections (Recommended)", 'OUTLINER_COLLECTION', 0),
            ('FLAT', "Root", "Direct export to project root", 'FILE_FOLDER', 1),
            ('BLEND', "Blend", "By Blend file name", 'FILE_BLEND', 2),
            ('BLEND_AND_COLL', "Hybrid", "Hybrid folder layout", 'ASSET_MANAGER', 3),
        ],
        default='COLLECTION'
    )

    bpy.types.Scene.godot_make_collisions = bpy.props.BoolProperty(
        name="Generate Collisions", default=True,
        description="Generates invisible static collision shapes (StaticBody3D)"
    )
    bpy.types.Scene.godot_collision_type = bpy.props.EnumProperty(
        name="Collision Type",
        items=[
            ('CONVEX', "Convex", "Optimized convex shape (-convcolonly)"),
            ('TRIMESH', "Trimesh", "Exact polygon mesh (-colonly)"),
        ],
        default='CONVEX'
    )
    bpy.types.Scene.godot_simplify_collision = bpy.props.BoolProperty(
        name="Simplify Collision",
        default=True,
        description="Reduces collision geometry polygon count using Decimate"
    )
    
    bpy.types.Scene.godot_collision_decimate_ratio = bpy.props.FloatProperty(
        name="Density",
        default=0.10,
        min=0.01,
        max=1.0,
        step=1,
        precision=2,
        subtype='FACTOR',
        description="Target polygon count ratio (0.10 = 10%)"
    )

    bpy.types.Scene.godot_center_mesh = bpy.props.BoolProperty(
        name="Center to Origin", default=True,
        description="Temporarily resets object position to (0,0,0) during export"
    )
    bpy.types.Scene.godot_export_anims = bpy.props.BoolProperty(
        name="Export Animations", default=True, 
        description="Exports skeletal animations"
    )
    bpy.types.Scene.godot_split_actions = bpy.props.BoolProperty(
        name="Split Actions", default=True,
        description="Exports each animation into Mesh@ActionName.glb"
    )
    bpy.types.Scene.godot_auto_loop = bpy.props.BoolProperty(
        name="Auto-Loop", default=True,
        description="Automatically appends -loop suffix to cyclic animations"
    )
    bpy.types.Scene.godot_clean_bones = bpy.props.BoolProperty(
        name="Deform Bones Only", default=True,
        description="Exports only deformation bones, stripping IK control bones"
    )

    # Фоновая проверка через 3 секунды после запуска
    bpy.app.timers.register(delayed_update_check, first_interval=3.0)

def unregister():
    global _draw_handle_3d
    if _draw_handle_3d is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handle_3d, 'WINDOW')
        _draw_handle_3d = None

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    del bpy.types.Scene.godot_project_select
    del bpy.types.Scene.godot_folder_structure
    del bpy.types.Scene.godot_make_collisions
    del bpy.types.Scene.godot_collision_type
    del bpy.types.Scene.godot_simplify_collision
    del bpy.types.Scene.godot_collision_decimate_ratio
    del bpy.types.Scene.godot_center_mesh
    del bpy.types.Scene.godot_export_anims
    del bpy.types.Scene.godot_split_actions
    del bpy.types.Scene.godot_auto_loop
    del bpy.types.Scene.godot_clean_bones

if __name__ == "__main__":
    register()