"""
DEM to 3D Print STL - HIGH PERFORMANCE VERSION
Optimized for systems with massive RAM (64GB+)

Version: 6.5 High-RAM (v65)
- FIX: Bowtie cutouts now use EXACT boolean solver for reliable cuts
  - All 8 cutouts now form consistently
  - Each cutout processed separately to avoid boolean failures
- NEW: Mounting holes - cylindrical cutouts near corners for back-mounting tiles
  - Configurable diameter (default 3mm) and uses same depth as bowtie cutouts
  - Positioned 10% in from each corner for secure mounting
- FIX: CityJSON buildings now correctly align to terrain Z elevation
- CityJSON building import support (LoD2 3D buildings from German cadastral data)
- Bowtie alignment cutouts for tile registration
- Building/road/trail shapefile support with shrinkwrap workflow
"""

bl_info = {
    "name": "DEM to 3D Print STL (High-RAM)",
    "author": "Christopher Jorgensen",
    "version": (6, 5, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > DEM Print",
    "description": "High-performance DEM processing for systems with 64GB+ RAM - Now with CityJSON support",
    "category": "Import-Export",
}

import bpy
import os
import time
import math
import json

try:
    import bmesh
    from mathutils import Vector
    from bpy.props import (
        StringProperty, 
        FloatProperty, 
        IntProperty, 
        BoolProperty,
        EnumProperty,
        PointerProperty
    )
    from bpy.types import Operator, Panel, PropertyGroup
except ImportError:
    pass


class DEMPrintProperties(PropertyGroup):
    """Properties for DEM processing"""
    
    dem_file: StringProperty(
        name="DEM File",
        description="Select your DEM file",
        default="",
        subtype='FILE_PATH'
    )
    
    output_width: FloatProperty(
        name="Output Width (mm)",
        description="Width of 3D print",
        default=200.0,
        min=10.0,
        max=1000.0
    )
    
    maintain_aspect: BoolProperty(
        name="Maintain Aspect Ratio",
        description="Keep terrain proportions",
        default=True
    )
    
    subdivision_levels: IntProperty(
        name="Subdivision Levels",
        description="Detail level - with 256GB RAM you can go HIGH!",
        default=11,
        min=1,
        max=15
    )
    
    extrude_depth: FloatProperty(
        name="Base Thickness (m)",
        description="Thickness of solid base (for mountains use 5000-10000m)",
        default=7000.0,
        min=100.0,
        max=20000.0
    )
    
    auto_cut_elevation: BoolProperty(
        name="Auto Calculate Cut",
        description="Automatically find lowest point",
        default=True
    )
    
    cut_elevation: FloatProperty(
        name="Manual Cut Elevation (m)",
        description="Manual cut elevation if auto is off",
        default=0.0
    )
    
    text_depth: FloatProperty(
        name="Text Depth (mm)",
        description="Deboss depth at final print scale (1mm recommended)",
        default=1.0,
        min=0.1,
        max=5.0
    )
    
    add_north_arrow: BoolProperty(
        name="Add North Arrow",
        description="Add debossed 'N' with arrow pointing north on bottom",
        default=True
    )
    
    # Bowtie alignment cutouts (triangular prisms)
    add_alignment_cutouts: BoolProperty(
        name="Add Alignment Cutouts",
        description="Add triangular bowtie cutouts on bottom edges for tile alignment",
        default=False
    )
    
    cutout_size: FloatProperty(
        name="Cutout Size (mm)",
        description="Size of the triangular cutout (width of triangle base)",
        default=5.0,
        min=1.0,
        max=20.0
    )
    
    cutout_depth: FloatProperty(
        name="Cutout Depth (mm)",
        description="How deep the cutout extends into the model from the bottom",
        default=3.0,
        min=0.5,
        max=10.0
    )
    
    cutout_inset: FloatProperty(
        name="Cutout Position (%)",
        description="Position of cutout along edge as percentage from corner (25 = quarter way)",
        default=25.0,
        min=5.0,
        max=45.0
    )
    
    cutout_edge_inset: FloatProperty(
        name="Edge Inset (%)",
        description="Triangle position relative to edge (100=apex at edge, 0=apex outside tile)",
        default=50.0,
        min=0.0,
        max=100.0
    )
    
    # Mounting holes for back-mounting tiles
    add_mounting_holes: BoolProperty(
        name="Add Mounting Holes",
        description="Add cylindrical holes near corners for mounting tiles from the back",
        default=False
    )
    
    mounting_hole_diameter: FloatProperty(
        name="Hole Diameter (mm)",
        description="Diameter of mounting holes (for screws or pins)",
        default=3.0,
        min=1.0,
        max=10.0
    )
    
    mounting_hole_inset: FloatProperty(
        name="Corner Inset (%)",
        description="Position of holes as percentage from corner (10 = 10% in from corner)",
        default=10.0,
        min=5.0,
        max=25.0
    )
    
    # Building shapefile support
    add_buildings: BoolProperty(
        name="Add Buildings",
        description="Import buildings from shapefile or CityJSON and project onto terrain",
        default=False
    )
    
    building_source: EnumProperty(
        name="Building Source",
        description="Choose the source format for building data",
        items=[
            ('SHAPEFILE', "Shapefile", "Import 2D building footprints from shapefile"),
            ('CITYJSON', "CityJSON", "Import 3D LoD2 buildings from CityJSON file"),
        ],
        default='SHAPEFILE'
    )
    
    building_shapefile: StringProperty(
        name="Building Shapefile",
        description="Path to shapefile containing building footprints",
        default="",
        subtype='FILE_PATH'
    )
    
    building_cityjson: StringProperty(
        name="CityJSON File",
        description="Path to CityJSON file containing 3D buildings (LoD2)",
        default="",
        subtype='FILE_PATH'
    )
    
    cityjson_use_lod: EnumProperty(
        name="LoD Level",
        description="Level of Detail to import from CityJSON",
        items=[
            ('highest', "Highest Available", "Use the highest LoD available for each building"),
            ('2', "LoD 2", "Use LoD 2 (detailed roof shapes)"),
            ('1', "LoD 1", "Use LoD 1 (block models)"),
            ('0', "LoD 0", "Use LoD 0 (footprints)"),
        ],
        default='highest'
    )
    
    building_height: FloatProperty(
        name="Building Height (m)",
        description="Height of buildings above terrain surface (for shapefile only)",
        default=12.0,
        min=1.0,
        max=100.0
    )
    
    building_depth: FloatProperty(
        name="Building Depth (m)",
        description="How far buildings extend below terrain surface",
        default=10.0,
        min=1.0,
        max=50.0
    )
    
    # Road shapefile support
    add_roads: BoolProperty(
        name="Add Roads",
        description="Import roads from shapefile and project onto terrain",
        default=False
    )
    
    road_shapefile: StringProperty(
        name="Road Shapefile",
        description="Path to shapefile containing road lines/polygons",
        default="",
        subtype='FILE_PATH'
    )
    
    road_width: FloatProperty(
        name="Road Width (m)",
        description="Width of roads (for line shapefiles)",
        default=40.0,
        min=1.0,
        max=100.0
    )
    
    road_height: FloatProperty(
        name="Road Height (m)",
        description="Height of roads above terrain surface",
        default=1.5,
        min=0.1,
        max=20.0
    )
    
    road_depth: FloatProperty(
        name="Road Depth (m)",
        description="How far roads extend below terrain surface",
        default=20.0,
        min=1.0,
        max=50.0
    )
    
    add_road_labels: BoolProperty(
        name="Add Road Labels",
        description="Generate street name labels as separate STL",
        default=False
    )
    
    road_label_size: FloatProperty(
        name="Label Size (m)",
        description="Height of road label text in meters",
        default=30.0,
        min=5.0,
        max=100.0
    )
    
    road_label_height: FloatProperty(
        name="Label Height (m)",
        description="Height/thickness of label text",
        default=5.0,
        min=1.0,
        max=20.0
    )
    
    road_label_min_length: FloatProperty(
        name="Min Road Length (m)",
        description="Minimum road segment length to label",
        default=100.0,
        min=10.0,
        max=500.0
    )
    
    # Trail shapefile support
    add_trails: BoolProperty(
        name="Add Trails",
        description="Import trails/paths from shapefile and project onto terrain",
        default=False
    )
    
    trail_shapefile: StringProperty(
        name="Trail Shapefile",
        description="Path to shapefile containing trail/path lines",
        default="",
        subtype='FILE_PATH'
    )
    
    trail_width: FloatProperty(
        name="Trail Width (m)",
        description="Width of trails (for line shapefiles)",
        default=10.0,
        min=0.5,
        max=50.0
    )
    
    trail_height: FloatProperty(
        name="Trail Height (m)",
        description="Height of trails above terrain surface",
        default=1.0,
        min=0.1,
        max=10.0
    )
    
    trail_depth: FloatProperty(
        name="Trail Depth (m)",
        description="How far trails extend below terrain surface",
        default=10.0,
        min=1.0,
        max=30.0
    )
    
    output_path: StringProperty(
        name="Output Folder",
        description="Where to save STL files",
        default="",
        subtype='DIR_PATH'
    )
    
    use_smooth_relief: BoolProperty(
        name="Smooth Relief",
        description="Use smooth interpolation",
        default=True
    )
    
    fill_nodata: BoolProperty(
        name="Fill NoData Values",
        description="Fill missing data",
        default=True
    )
    
    # Batch processing
    batch_folder: StringProperty(
        name="Batch Input Folder",
        description="Folder containing DEM files to process",
        default="",
        subtype='DIR_PATH'
    )
    
    batch_recursive: BoolProperty(
        name="Include Subfolders",
        description="Search for DEM files in subfolders too",
        default=False
    )


class DEMPRINT_OT_Process(Operator):
    """Process DEM to 3D printable STL - HIGH PERFORMANCE"""
    bl_idname = "demprint.process"
    bl_label = "Process DEM to STL"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        props = context.scene.dem_print_props
        if not props.dem_file or not os.path.exists(props.dem_file):
            return False
        
        valid_extensions = ['.tif', '.tiff', '.asc', '.dem', '.hgt', '.img']
        file_ext = os.path.splitext(props.dem_file)[1].lower()
        
        return file_ext in valid_extensions
    
    def execute(self, context):
        props = context.scene.dem_print_props
        
        start_time = time.time()
        
        if not hasattr(bpy.ops, 'importgis') or not hasattr(bpy.ops.importgis, 'georaster'):
            self.report({'ERROR'}, "BlenderGIS not found!")
            return {'CANCELLED'}
        
        print("\n" + "="*70)
        print("DEM TO STL PROCESSING - HIGH PERFORMANCE MODE v5.9")
        print("="*70)
        print(f"Subdivision level: {props.subdivision_levels}")
        print(f"Input: {os.path.basename(props.dem_file)}")
        print(f"Output width: {props.output_width}mm")
        if props.add_buildings:
            if props.building_source == 'CITYJSON' and props.building_cityjson:
                print(f"Buildings (CityJSON): {os.path.basename(props.building_cityjson)}")
            elif props.building_source == 'SHAPEFILE' and props.building_shapefile:
                print(f"Buildings (Shapefile): {os.path.basename(props.building_shapefile)}")
        if props.add_roads and props.road_shapefile:
            print(f"Roads: {os.path.basename(props.road_shapefile)}")
        if props.add_trails and props.trail_shapefile:
            print(f"Trails: {os.path.basename(props.trail_shapefile)}")
        print("="*70 + "\n")
        
        try:
            # Step 1: Import DEM
            self.report({'INFO'}, "Step 1/11: Importing DEM...")
            dem_obj = self.import_dem(context, props)
            if not dem_obj:
                return {'CANCELLED'}
            
            dem_obj_name = dem_obj.name
            dem_width = dem_obj.dimensions.x
            dem_height = dem_obj.dimensions.y
            
            print(f"✓ Imported: {dem_width:.0f}×{dem_height:.0f}m")
            
            # Step 2: Set subdivision
            self.report({'INFO'}, f"Step 2/11: Setting subdivision (level {props.subdivision_levels})...")
            self.set_subdivision_level(dem_obj, props.subdivision_levels)
            
            # Step 3: Apply modifiers
            self.report({'INFO'}, "Step 3/11: Applying modifiers...")
            print("  This is the slowest step - please be patient...")
            
            bpy.context.view_layer.update()
            
            if not self.apply_modifiers(dem_obj):
                self.report({'ERROR'}, "Failed to apply modifiers")
                return {'CANCELLED'}
            
            dem_obj = bpy.data.objects.get(dem_obj_name)
            final_vertices = len(dem_obj.data.vertices)
            print(f"✓ Modifiers applied: {final_vertices:,} vertices")
            
            # Step 4: Extrude base
            self.report({'INFO'}, f"Step 4/11: Creating base ({props.extrude_depth}m)...")
            self.extrude_base(dem_obj, props.extrude_depth)
            
            # Step 5: Cut flat bottom
            self.report({'INFO'}, "Step 5/11: Cutting flat bottom...")
            cut_elev = self.calculate_cut_elevation(dem_obj, props)
            print(f"  Cutting at elevation: {cut_elev:.2f}m")
            self.cut_flat_bottom(dem_obj, cut_elev)
            
            dem_obj = bpy.data.objects.get(dem_obj_name)
            
            # Step 6: Add buildings (before scaling, after terrain is complete)
            building_obj = None
            if props.add_buildings:
                self.report({'INFO'}, "Step 6/11: Adding buildings...")
                dem_obj = bpy.data.objects.get(dem_obj_name)
                
                if props.building_source == 'CITYJSON' and props.building_cityjson and os.path.exists(props.building_cityjson):
                    building_obj = self.add_buildings_cityjson(context, dem_obj, props)
                elif props.building_source == 'SHAPEFILE' and props.building_shapefile and os.path.exists(props.building_shapefile):
                    building_obj = self.add_buildings(context, dem_obj, props)
                else:
                    print("  No valid building file specified")
            else:
                self.report({'INFO'}, "Step 6/11: Skipping buildings...")
            
            # Step 7: Add roads (before scaling, after terrain is complete)
            road_obj = None
            if props.add_roads and props.road_shapefile and os.path.exists(props.road_shapefile):
                self.report({'INFO'}, "Step 7/12: Adding roads...")
                dem_obj = bpy.data.objects.get(dem_obj_name)
                road_obj = self.add_roads(context, dem_obj, props)
            else:
                self.report({'INFO'}, "Step 7/12: Skipping roads...")
            
            # Step 8: Add trails (before scaling, after terrain is complete)
            trail_obj = None
            if props.add_trails and props.trail_shapefile and os.path.exists(props.trail_shapefile):
                self.report({'INFO'}, "Step 8/12: Adding trails...")
                dem_obj = bpy.data.objects.get(dem_obj_name)
                trail_obj = self.add_trails(context, dem_obj, props)
            else:
                self.report({'INFO'}, "Step 8/12: Skipping trails...")
            
            # Step 8b: Add road labels if enabled
            labels_obj = None
            if props.add_road_labels and props.road_shapefile and os.path.exists(props.road_shapefile):
                self.report({'INFO'}, "Generating road labels...")
                dem_obj = bpy.data.objects.get(dem_obj_name)
                labels_obj = self.add_road_labels(context, dem_obj, road_obj, props)
            
            # Step 9: Add text
            self.report({'INFO'}, "Step 9/12: Adding debossed text...")
            filename = os.path.splitext(os.path.basename(props.dem_file))[0]
            dem_obj = bpy.data.objects.get(dem_obj_name)
            self.add_text_before_scale(context, dem_obj, filename, props)
            
            dem_obj = bpy.data.objects.get(dem_obj_name)
            if dem_obj is None or len(dem_obj.data.vertices) == 0:
                self.report({'ERROR'}, "Text boolean destroyed mesh!")
                return {'CANCELLED'}
            
            # Step 10: Add alignment cutouts
            if props.add_alignment_cutouts:
                self.report({'INFO'}, "Step 10/12: Adding bowtie alignment cutouts...")
                dem_obj = bpy.data.objects.get(dem_obj_name)
                self.add_alignment_cutouts(context, dem_obj, props)
            else:
                self.report({'INFO'}, "Step 10/12: Skipping alignment cutouts...")
            
            # Step 10b: Add mounting holes
            if props.add_mounting_holes:
                self.report({'INFO'}, "Adding mounting holes...")
                dem_obj = bpy.data.objects.get(dem_obj_name)
                self.add_mounting_holes(context, dem_obj, props)
            
            # Step 11: Scale to print size
            self.report({'INFO'}, "Step 11/12: Scaling to print size...")
            dem_obj = bpy.data.objects.get(dem_obj_name)
            scale = self.calculate_scale(dem_obj, props)
            self.scale_object(dem_obj, scale)
            
            # Scale buildings too if they exist
            if building_obj:
                building_obj.scale = scale
                bpy.context.view_layer.objects.active = building_obj
                bpy.ops.object.transform_apply(scale=True)
                print(f"  Buildings scaled to match terrain")
            
            # Scale roads too if they exist
            if road_obj:
                road_obj.scale = scale
                bpy.context.view_layer.objects.active = road_obj
                bpy.ops.object.transform_apply(scale=True)
                print(f"  Roads scaled to match terrain")
            
            # Scale trails too if they exist
            if trail_obj:
                trail_obj.scale = scale
                bpy.context.view_layer.objects.active = trail_obj
                bpy.ops.object.transform_apply(scale=True)
                print(f"  Trails scaled to match terrain")
            
            # Scale road labels too if they exist
            if labels_obj:
                labels_obj.scale = scale
                bpy.context.view_layer.objects.active = labels_obj
                bpy.ops.object.transform_apply(scale=True)
                print(f"  Road labels scaled to match terrain")
            
            # Assign materials for visualization
            # Colors: terrain=dark green, roads=black, labels=white, trails=brown, buildings=red
            print("  Assigning visualization materials...")
            
            mat_terrain = self.create_material("Terrain_Green", (0.1, 0.3, 0.1))  # Dark green
            mat_roads = self.create_material("Roads_Black", (0.05, 0.05, 0.05))   # Black
            mat_labels = self.create_material("Labels_White", (1.0, 1.0, 1.0))    # White
            mat_trails = self.create_material("Trails_Brown", (0.4, 0.25, 0.1))   # Brown
            mat_buildings = self.create_material("Buildings_Red", (0.7, 0.1, 0.1)) # Red
            
            dem_obj = bpy.data.objects.get(dem_obj_name)
            self.assign_material(dem_obj, mat_terrain)
            
            if building_obj:
                self.assign_material(building_obj, mat_buildings)
            if road_obj:
                self.assign_material(road_obj, mat_roads)
            if trail_obj:
                self.assign_material(trail_obj, mat_trails)
            if labels_obj:
                self.assign_material(labels_obj, mat_labels)
            
            # Step 12: Export
            self.report({'INFO'}, "Step 12/12: Exporting STL...")
            dem_obj = bpy.data.objects.get(dem_obj_name)
            output_file = self.export_stl(dem_obj, props, "_terrain")
            
            # Export buildings separately if they exist
            if building_obj:
                building_output = self.export_stl(building_obj, props, "_buildings")
                print(f"  Buildings exported: {os.path.basename(building_output)}")
            
            # Export roads separately if they exist
            if road_obj:
                road_output = self.export_stl(road_obj, props, "_roads")
                print(f"  Roads exported: {os.path.basename(road_output)}")
            
            # Export trails separately if they exist
            if trail_obj:
                trail_output = self.export_stl(trail_obj, props, "_trails")
                print(f"  Trails exported: {os.path.basename(trail_output)}")
            
            # Export road labels separately if they exist
            if labels_obj:
                labels_output = self.export_stl(labels_obj, props, "_road_labels")
                print(f"  Road labels exported: {os.path.basename(labels_output)}")
            
            elapsed_time = time.time() - start_time
            self.print_summary(dem_obj, output_file, dem_width, dem_height, final_vertices, elapsed_time)
            
            if elapsed_time < 60:
                time_str = f"{elapsed_time:.1f} seconds"
            elif elapsed_time < 3600:
                time_str = f"{int(elapsed_time // 60)}m {int(elapsed_time % 60)}s"
            else:
                time_str = f"{int(elapsed_time // 3600)}h {int((elapsed_time % 3600) // 60)}m"
            
            self.report({'INFO'}, f"✓ SUCCESS! {os.path.basename(output_file)} ({time_str})")
            
            return {'FINISHED'}
            
        except Exception as e:
            import traceback
            self.report({'ERROR'}, f"Error: {str(e)}")
            print("\n" + "="*70)
            print("ERROR:")
            traceback.print_exc()
            print("="*70 + "\n")
            return {'CANCELLED'}
    
    def create_material(self, name, color):
        """Create a material with the given name and RGB color (0-1 range)"""
        mat = bpy.data.materials.get(name)
        if mat is None:
            mat = bpy.data.materials.new(name=name)
        mat.use_nodes = True
        
        # Get the principled BSDF node
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            bsdf.inputs["Base Color"].default_value = (color[0], color[1], color[2], 1.0)
        
        # Also set viewport display color for Solid shading mode
        mat.diffuse_color = (color[0], color[1], color[2], 1.0)
        
        return mat
    
    def assign_material(self, obj, material):
        """Assign a material to an object"""
        if obj is None:
            return
        
        # Clear existing materials
        obj.data.materials.clear()
        # Add the new material
        obj.data.materials.append(material)
        
        # Set object color for viewport solid mode with Object color option
        obj.color = material.diffuse_color
    
    def import_dem(self, context, props):
        """Import DEM using BlenderGIS"""
        before = set(context.scene.objects)
        
        try:
            print("Importing DEM file with BlenderGIS...")
            
            result = bpy.ops.importgis.georaster(
                filepath=props.dem_file,
                importMode='DEM',
                subdivision='subsurf',
                demInterpolation=bool(props.use_smooth_relief),
                fillNodata=bool(props.fill_nodata)
            )
            
            if result != {'FINISHED'}:
                print(f"Import failed: {result}")
                return None
                
        except Exception as e:
            print(f"Import error: {str(e)}")
            return None
        
        after = set(context.scene.objects)
        new = after - before
        
        if len(new) == 0:
            return None
        
        dem_obj = list(new)[0]
        print(f"  Imported object: {dem_obj.name}")
        
        return dem_obj
    
    def set_subdivision_level(self, obj, levels):
        """Set subdivision level"""
        for mod in obj.modifiers:
            if mod.type == 'SUBSURF':
                mod.levels = levels
                mod.render_levels = levels
                print(f"✓ Updated subdivision: {levels} levels")
                return
        
        mod = obj.modifiers.new(name="Subdivision", type='SUBSURF')
        mod.levels = levels
        mod.render_levels = levels
        print(f"✓ Added subdivision: {levels} levels")
        
        bpy.context.view_layer.update()
    
    def apply_modifiers(self, obj):
        """Apply all modifiers"""
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        
        modifiers = list(obj.modifiers)
        total = len(modifiers)
        
        for i, mod in enumerate(modifiers):
            print(f"  Applying modifier {i+1}/{total}: {mod.name} ({mod.type})...")
            
            try:
                bpy.ops.object.modifier_apply(modifier=mod.name)
                bpy.context.view_layer.update()
                print(f"    ✓ Applied - {len(obj.data.vertices):,} vertices")
            except Exception as e:
                print(f"    ✗ Failed: {str(e)}")
                return False
        
        return True
    
    def extrude_base(self, obj, depth):
        """Extrude to create solid base"""
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.extrude_region_move(
            TRANSFORM_OT_translate={"value": (0, 0, -depth)}
        )
        bpy.ops.object.mode_set(mode='OBJECT')
        print(f"✓ Base extruded: {depth}m")
    
    def calculate_cut_elevation(self, obj, props):
        """Calculate cut elevation"""
        if props.auto_cut_elevation:
            min_z = min((obj.matrix_world @ v.co).z for v in obj.data.vertices)
            return min_z - 1.0
        return props.cut_elevation
    
    def cut_flat_bottom(self, obj, cut_elevation):
        """Boolean cut for flat bottom
        
        Creates a very tall cube that extends far below the cut elevation
        to ensure complete cutting regardless of terrain height.
        """
        bbox = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
        min_x = min(v.x for v in bbox)
        max_x = max(v.x for v in bbox)
        min_y = min(v.y for v in bbox)
        max_y = max(v.y for v in bbox)
        min_z = min(v.z for v in bbox)
        max_z = max(v.z for v in bbox)
        
        model_width = max(max_x - min_x, max_y - min_y)
        model_height = max_z - min_z
        
        # Make cutter much larger than model in all dimensions
        cutter_xy_size = model_width * 3
        # Cutter height needs to extend from well below cut_elevation to handle any terrain
        # Use 10x the model height or 50000m, whichever is larger
        cutter_z_size = max(model_height * 10, 50000)
        
        # Position cutter so its TOP is at cut_elevation
        cutter_z = cut_elevation - (cutter_z_size / 2)
        cutter_center_x = (min_x + max_x) / 2
        cutter_center_y = (min_y + max_y) / 2
        
        print(f"  Cutter: {cutter_xy_size:.0f}m x {cutter_xy_size:.0f}m x {cutter_z_size:.0f}m")
        print(f"  Cutter Z range: {cutter_z - cutter_z_size/2:.0f} to {cutter_z + cutter_z_size/2:.0f}")
        
        bpy.ops.mesh.primitive_cube_add(
            size=1,
            location=(cutter_center_x, cutter_center_y, cutter_z)
        )
        cutter = bpy.context.active_object
        cutter.name = "Bottom_Cutter"
        cutter.scale = (cutter_xy_size, cutter_xy_size, cutter_z_size)
        bpy.ops.object.transform_apply(scale=True)
        
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        
        bool_mod = obj.modifiers.new(name="Boolean_FlatBottom", type='BOOLEAN')
        bool_mod.operation = 'DIFFERENCE'
        bool_mod.object = cutter
        bool_mod.solver = 'EXACT'
        
        try:
            bpy.ops.object.modifier_apply(modifier=bool_mod.name)
        except:
            # Fallback to FAST solver
            bool_mod = obj.modifiers.new(name="Boolean_Retry", type='BOOLEAN')
            bool_mod.operation = 'DIFFERENCE'
            bool_mod.object = cutter
            bool_mod.solver = 'FAST'
            bpy.ops.object.modifier_apply(modifier=bool_mod.name)
        
        bpy.data.objects.remove(cutter, do_unlink=True)
        print(f"✓ Flat bottom at {cut_elevation:.2f}m")
    
    def make_manifold(self, obj):
        """Fix non-manifold geometry for clean STL export"""
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        
        # Remove doubles/merge close vertices
        bpy.ops.mesh.remove_doubles(threshold=0.001)
        
        # Fill holes
        bpy.ops.mesh.select_all(action='DESELECT')
        bpy.ops.mesh.select_non_manifold(extend=False)
        
        # Try to fill non-manifold edges
        try:
            bpy.ops.mesh.fill_holes(sides=0)
        except:
            pass
        
        # Delete loose geometry
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.delete_loose()
        
        # Recalculate normals
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.normals_make_consistent(inside=False)
        
        bpy.ops.object.mode_set(mode='OBJECT')
    
    def add_buildings(self, context, dem_obj, props):
        """Import buildings from shapefile and project onto terrain
        
        Workflow matching roads/trails:
        1. Import shapefile (handle CRS issues)
        2. Pre-prune vertices far outside terrain (keep connected)
        3. Subdivide to densify
        4. Lift and shrinkwrap
        5. Prune vertices that didn't shrinkwrap
        6. Bisect cut at terrain boundaries
        7. Move below terrain and extrude upward
        """
        print(f"  Importing buildings from: {os.path.basename(props.building_shapefile)}")
        
        before = set(context.scene.objects)
        imported = False
        
        # Method 1: Try importing with default settings
        try:
            result = bpy.ops.importgis.shapefile(filepath=props.building_shapefile)
            if result == {'FINISHED'}:
                imported = True
        except Exception as e:
            print(f"  Standard import failed: {str(e)[:100]}")
        
        # Method 2: Try with explicit CRS settings if first attempt failed
        if not imported:
            print("  Attempting import with explicit CRS (EPSG:3857)...")
            try:
                # Try setting both source and target CRS to same value to skip reprojection
                result = bpy.ops.importgis.shapefile(
                    filepath=props.building_shapefile,
                    shpCRS='EPSG:3857',  # Assume source is EPSG:3857
                )
                if result == {'FINISHED'}:
                    imported = True
            except Exception as e:
                print(f"  EPSG:3857 import failed: {str(e)[:100]}")
        
        # Method 3: Try with WGS84
        if not imported:
            print("  Attempting import with EPSG:4326 (WGS84)...")
            try:
                result = bpy.ops.importgis.shapefile(
                    filepath=props.building_shapefile,
                    shpCRS='EPSG:4326',
                )
                if result == {'FINISHED'}:
                    imported = True
            except Exception as e:
                print(f"  EPSG:4326 import failed: {str(e)[:100]}")
        
        # Method 4: Try direct geometry import using pyshp if BlenderGIS fails
        if not imported:
            print("  Attempting direct shapefile read...")
            try:
                imported = self.import_shapefile_direct(context, props.building_shapefile)
            except Exception as e:
                print(f"  Direct import failed: {str(e)[:100]}")
        
        if not imported:
            print("  ERROR: Could not import shapefile")
            print("  TIP: Fix the shapefile's .prj file in QGIS:")
            print("       1. Open shapefile in QGIS")
            print("       2. Right-click layer → Export → Save Features As")
            print("       3. Set CRS to EPSG:3857")
            print("       4. Save as new shapefile")
            return None
        
        after = set(context.scene.objects)
        new_objs = list(after - before)
        
        if not new_objs:
            print("  No objects imported from shapefile")
            return None
        
        building_obj = new_objs[0]
        building_obj.name = "Buildings"
        initial_verts = len(building_obj.data.vertices)
        print(f"  Imported {initial_verts:,} vertices")
        
        if initial_verts == 0:
            print("  WARNING: Shapefile imported but has no vertices")
            bpy.data.objects.remove(building_obj, do_unlink=True)
            return None
        
        # Get terrain bounds and max Z
        terrain_bbox = [dem_obj.matrix_world @ Vector(corner) for corner in dem_obj.bound_box]
        terrain_min_x = min(v.x for v in terrain_bbox)
        terrain_max_x = max(v.x for v in terrain_bbox)
        terrain_min_y = min(v.y for v in terrain_bbox)
        terrain_max_y = max(v.y for v in terrain_bbox)
        terrain_max_z = max((dem_obj.matrix_world @ v.co).z for v in dem_obj.data.vertices)
        terrain_min_z = min((dem_obj.matrix_world @ v.co).z for v in dem_obj.data.vertices)
        
        print(f"  Terrain bounds: X[{terrain_min_x:.0f}, {terrain_max_x:.0f}] Y[{terrain_min_y:.0f}, {terrain_max_y:.0f}]")
        print(f"  Terrain Z range: [{terrain_min_z:.0f}, {terrain_max_z:.0f}]")
        
        # Check building bounds
        bldg_bbox = [building_obj.matrix_world @ Vector(corner) for corner in building_obj.bound_box]
        bldg_min_x = min(v.x for v in bldg_bbox)
        bldg_max_x = max(v.x for v in bldg_bbox)
        bldg_min_y = min(v.y for v in bldg_bbox)
        bldg_max_y = max(v.y for v in bldg_bbox)
        print(f"  Building bounds: X[{bldg_min_x:.0f}, {bldg_max_x:.0f}] Y[{bldg_min_y:.0f}, {bldg_max_y:.0f}]")
        
        # Pre-prune: Remove vertices far outside terrain, but keep connected geometry
        margin = 500  # Keep buildings near edges
        
        bpy.context.view_layer.objects.active = building_obj
        bpy.ops.object.select_all(action='DESELECT')
        building_obj.select_set(True)
        
        mesh = building_obj.data
        
        # Identify vertices inside extended bounds
        inside_bounds = set()
        for i, vert in enumerate(mesh.vertices):
            world_co = building_obj.matrix_world @ vert.co
            if (terrain_min_x - margin <= world_co.x <= terrain_max_x + margin and
                terrain_min_y - margin <= world_co.y <= terrain_max_y + margin):
                inside_bounds.add(i)
        
        # Find vertices connected to inside vertices
        connected_to_inside = set(inside_bounds)
        for edge in mesh.edges:
            v0, v1 = edge.vertices
            if v0 in inside_bounds or v1 in inside_bounds:
                connected_to_inside.add(v0)
                connected_to_inside.add(v1)
        
        # Also check faces (buildings are polygons)
        for face in mesh.polygons:
            face_verts = list(face.vertices)
            if any(v in inside_bounds for v in face_verts):
                connected_to_inside.update(face_verts)
        
        # Select disconnected vertices
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='DESELECT')
        bpy.ops.object.mode_set(mode='OBJECT')
        
        outside_verts = 0
        for i, vert in enumerate(mesh.vertices):
            if i not in connected_to_inside:
                vert.select = True
                outside_verts += 1
        
        if outside_verts > 0:
            print(f"  Pre-pruning {outside_verts:,} disconnected vertices outside terrain")
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.delete(type='VERT')
            bpy.ops.object.mode_set(mode='OBJECT')
            print(f"  After pre-prune: {len(building_obj.data.vertices):,} vertices")
        
        if len(building_obj.data.vertices) == 0:
            print("  WARNING: No building vertices within terrain bounds")
            bpy.data.objects.remove(building_obj, do_unlink=True)
            return None
        
        # Subdivide to densify (helps with shrinkwrap on large buildings)
        print(f"  Subdividing to densify...")
        bpy.context.view_layer.objects.active = building_obj
        bpy.ops.object.select_all(action='DESELECT')
        building_obj.select_set(True)
        
        subsurf = building_obj.modifiers.new(name="Subdivide", type='SUBSURF')
        subsurf.subdivision_type = 'SIMPLE'
        subsurf.levels = 3  # Less than roads since buildings are already denser
        subsurf.render_levels = 3
        bpy.ops.object.modifier_apply(modifier=subsurf.name)
        
        print(f"  After subdivision: {len(building_obj.data.vertices):,} vertices")
        
        # Lift above terrain
        lift_height = terrain_max_z + 1000
        building_obj.location.z = lift_height
        bpy.ops.object.transform_apply(location=True)
        print(f"  Lifted buildings to Z={lift_height:.0f}m")
        
        # Apply shrinkwrap modifier
        shrinkwrap = building_obj.modifiers.new(name="Shrinkwrap", type='SHRINKWRAP')
        shrinkwrap.target = dem_obj
        shrinkwrap.wrap_method = 'PROJECT'
        shrinkwrap.use_project_z = True
        shrinkwrap.use_negative_direction = True
        shrinkwrap.use_positive_direction = False
        
        bpy.ops.object.modifier_apply(modifier=shrinkwrap.name)
        print(f"  Shrinkwrap applied")
        
        # Prune vertices that didn't shrinkwrap (still high)
        threshold_z = terrain_max_z + 100
        
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='DESELECT')
        bpy.ops.object.mode_set(mode='OBJECT')
        
        mesh = building_obj.data
        high_verts = 0
        for vert in mesh.vertices:
            world_co = building_obj.matrix_world @ vert.co
            if world_co.z > threshold_z:
                vert.select = True
                high_verts += 1
        
        if high_verts > 0:
            print(f"  Found {high_verts:,} vertices that didn't shrinkwrap")
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.delete(type='VERT')
            bpy.ops.object.mode_set(mode='OBJECT')
        
        remaining_verts = len(building_obj.data.vertices)
        print(f"  After shrinkwrap pruning: {remaining_verts:,} vertices")
        
        if remaining_verts == 0:
            print("  WARNING: No building vertices remaining")
            bpy.data.objects.remove(building_obj, do_unlink=True)
            return None
        
        # Bisect on all 4 sides to cleanly cut at terrain boundary
        print(f"  Cutting buildings at terrain boundaries...")
        bpy.context.view_layer.objects.active = building_obj
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        
        # Cut at min X (West edge)
        bpy.ops.mesh.bisect(
            plane_co=(terrain_min_x, 0, 0),
            plane_no=(1, 0, 0),
            clear_inner=True,
            clear_outer=False
        )
        bpy.ops.mesh.select_all(action='SELECT')
        
        # Cut at max X (East edge)
        bpy.ops.mesh.bisect(
            plane_co=(terrain_max_x, 0, 0),
            plane_no=(-1, 0, 0),
            clear_inner=True,
            clear_outer=False
        )
        bpy.ops.mesh.select_all(action='SELECT')
        
        # Cut at min Y (South edge)
        bpy.ops.mesh.bisect(
            plane_co=(0, terrain_min_y, 0),
            plane_no=(0, 1, 0),
            clear_inner=True,
            clear_outer=False
        )
        bpy.ops.mesh.select_all(action='SELECT')
        
        # Cut at max Y (North edge)
        bpy.ops.mesh.bisect(
            plane_co=(0, terrain_max_y, 0),
            plane_no=(0, -1, 0),
            clear_inner=True,
            clear_outer=False
        )
        
        bpy.ops.object.mode_set(mode='OBJECT')
        print(f"  After boundary cuts: {len(building_obj.data.vertices):,} vertices")
        
        # Remove loose geometry
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.delete_loose()
        bpy.ops.object.mode_set(mode='OBJECT')
        
        final_verts = len(building_obj.data.vertices)
        if final_verts == 0:
            print("  WARNING: No building geometry remaining")
            bpy.data.objects.remove(building_obj, do_unlink=True)
            return None
        
        print(f"  Final building vertices: {final_verts:,}")
        
        # Move buildings below terrain surface
        building_obj.location.z = -props.building_depth
        bpy.ops.object.transform_apply(location=True)
        print(f"  Moved buildings {props.building_depth}m below surface")
        
        # Extrude buildings upward
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        
        extrude_height = props.building_depth + props.building_height
        bpy.ops.mesh.extrude_region_move(
            TRANSFORM_OT_translate={"value": (0, 0, extrude_height)}
        )
        bpy.ops.object.mode_set(mode='OBJECT')
        
        print(f"  Extruded buildings {extrude_height}m ({props.building_height}m above terrain)")
        print(f"✓ Buildings added: {len(building_obj.data.vertices):,} vertices")
        
        return building_obj
    
    def add_buildings_cityjson(self, context, dem_obj, props):
        """Import 3D buildings from CityJSON file
        
        CityJSON files contain full 3D geometry (LoD2) with roof shapes.
        This method:
        1. Parses CityJSON and extracts building geometry
        2. Creates mesh objects for each building
        3. Transforms coordinates to match terrain's Blender position
        4. Calculates Z offset to align buildings with terrain surface
        5. Clips to terrain bounds
        """
        print(f"  Importing CityJSON buildings from: {os.path.basename(props.building_cityjson)}")
        
        # Get terrain bounds in Blender coordinates
        terrain_bbox = [dem_obj.matrix_world @ Vector(corner) for corner in dem_obj.bound_box]
        terrain_min_x = min(v.x for v in terrain_bbox)
        terrain_max_x = max(v.x for v in terrain_bbox)
        terrain_min_y = min(v.y for v in terrain_bbox)
        terrain_max_y = max(v.y for v in terrain_bbox)
        terrain_min_z = min((dem_obj.matrix_world @ v.co).z for v in dem_obj.data.vertices)
        terrain_max_z = max((dem_obj.matrix_world @ v.co).z for v in dem_obj.data.vertices)
        
        terrain_width = terrain_max_x - terrain_min_x
        terrain_height = terrain_max_y - terrain_min_y
        
        print(f"  Terrain Blender bounds: X[{terrain_min_x:.0f}, {terrain_max_x:.0f}] Y[{terrain_min_y:.0f}, {terrain_max_y:.0f}]")
        print(f"  Terrain Z range: [{terrain_min_z:.0f}, {terrain_max_z:.0f}]")
        
        # Get real-world origin from BlenderGIS geoscene
        # BlenderGIS stores the CRS origin in scene properties
        geoscn_origin_x = 0
        geoscn_origin_y = 0
        
        # Try to get from BlenderGIS scene properties
        scene = context.scene
        if hasattr(scene, 'geoscn'):
            geoscn = scene.geoscn
            if hasattr(geoscn, 'crsx') and hasattr(geoscn, 'crsy'):
                geoscn_origin_x = geoscn.crsx
                geoscn_origin_y = geoscn.crsy
                print(f"  BlenderGIS origin: ({geoscn_origin_x:.0f}, {geoscn_origin_y:.0f})")
        
        # If BlenderGIS origin not found, try to extract from DEM filename
        # Format: dgm1_32_XXX_YYYY.tif where XXX is easting/1000, YYYY is northing/1000
        if geoscn_origin_x == 0 and geoscn_origin_y == 0:
            dem_name = os.path.basename(props.dem_file)
            import re
            match = re.search(r'(\d+)_(\d+)_(\d+)_(\d+)', dem_name)
            if match:
                # Pattern: dgm1_32_XXX_YYYY
                easting_km = int(match.group(3))
                northing_km = int(match.group(4))
                # DEM tiles are 1km x 1km, coordinates are SW corner
                geoscn_origin_x = easting_km * 1000 + terrain_width / 2
                geoscn_origin_y = northing_km * 1000 + terrain_height / 2
                print(f"  Extracted origin from filename: ({geoscn_origin_x:.0f}, {geoscn_origin_y:.0f})")
        
        # Calculate real-world bounds of terrain
        real_min_x = geoscn_origin_x + terrain_min_x
        real_max_x = geoscn_origin_x + terrain_max_x
        real_min_y = geoscn_origin_y + terrain_min_y
        real_max_y = geoscn_origin_y + terrain_max_y
        
        print(f"  Terrain real-world bounds: X[{real_min_x:.0f}, {real_max_x:.0f}] Y[{real_min_y:.0f}, {real_max_y:.0f}]")
        
        # Load CityJSON file
        try:
            with open(props.building_cityjson, 'r', encoding='utf-8') as f:
                cityjson = json.load(f)
        except Exception as e:
            print(f"  ERROR: Could not load CityJSON file: {e}")
            return None
        
        # Check CityJSON version and structure
        cj_version = cityjson.get('version', 'unknown')
        print(f"  CityJSON version: {cj_version}")
        
        # Get transform parameters (CityJSON uses compressed coordinates)
        transform = cityjson.get('transform', {})
        scale = transform.get('scale', [1, 1, 1])
        translate = transform.get('translate', [0, 0, 0])
        
        print(f"  CityJSON Transform - Scale: {scale}, Translate: {translate}")
        
        # Get vertices (shared vertex list)
        vertices_raw = cityjson.get('vertices', [])
        if not vertices_raw:
            print("  ERROR: No vertices found in CityJSON")
            return None
        
        # First pass: analyze CityJSON Z range to determine offset needed
        # Sample some vertices to get the Z range of buildings
        sample_z_values = []
        step = max(1, len(vertices_raw) // 1000)  # Sample ~1000 vertices
        for i in range(0, len(vertices_raw), step):
            v = vertices_raw[i]
            real_z = v[2] * scale[2] + translate[2]
            sample_z_values.append(real_z)
        
        cityjson_min_z = min(sample_z_values)
        cityjson_max_z = max(sample_z_values)
        
        print(f"  CityJSON Z range (real-world): [{cityjson_min_z:.0f}, {cityjson_max_z:.0f}]")
        
        # Calculate Z offset: the difference between CityJSON ground level and terrain elevation
        # CityJSON buildings typically have their ground level at real-world elevation
        # BlenderGIS terrain also uses real-world elevation
        # BUT: there may be a systematic offset between the two datasets
        
        # Method: Compare the minimum Z of CityJSON (likely ground floors) with terrain Z range
        # If CityJSON min Z is close to terrain Z range, no offset needed
        # If there's a large discrepancy, calculate offset
        
        z_offset = 0.0
        
        # Check if CityJSON Z values are in a completely different range than terrain
        # This indicates the datasets use different Z references
        if cityjson_min_z > terrain_max_z + 100 or cityjson_max_z < terrain_min_z - 100:
            # Large mismatch - likely different Z reference systems
            # Estimate offset by aligning CityJSON ground (min Z) with terrain average
            terrain_avg_z = (terrain_min_z + terrain_max_z) / 2
            z_offset = terrain_avg_z - cityjson_min_z
            print(f"  Z MISMATCH DETECTED: CityJSON and terrain use different Z references")
            print(f"  Calculated Z offset: {z_offset:.1f}m")
        else:
            # Z ranges overlap - check if fine-tuning is needed
            # The CityJSON ground floor Z should be close to terrain Z at the same XY location
            print(f"  Z ranges compatible - buildings should align with terrain")
        
        # Transform vertices to real-world coordinates, then to Blender coordinates
        # Real-world coord = raw * scale + translate
        # Blender coord = real-world coord - geoscn_origin (for X, Y) + z_offset (for Z)
        vertices = []
        for v in vertices_raw:
            real_x = v[0] * scale[0] + translate[0]
            real_y = v[1] * scale[1] + translate[1]
            real_z = v[2] * scale[2] + translate[2]
            # Transform to Blender coordinates (relative to terrain center)
            blender_x = real_x - geoscn_origin_x
            blender_y = real_y - geoscn_origin_y
            blender_z = real_z + z_offset  # Apply Z offset
            vertices.append((blender_x, blender_y, blender_z))
        
        print(f"  Total vertices in file: {len(vertices):,}")
        
        # Sample vertex to verify transformation
        if vertices:
            sample_real = (vertices_raw[0][0] * scale[0] + translate[0],
                          vertices_raw[0][1] * scale[1] + translate[1])
            sample_blender = (vertices[0][0], vertices[0][1])
            print(f"  Sample vertex - Real: ({sample_real[0]:.0f}, {sample_real[1]:.0f}) -> Blender: ({sample_blender[0]:.0f}, {sample_blender[1]:.0f})")
        
        # Get city objects (buildings)
        city_objects = cityjson.get('CityObjects', {})
        
        # Filter for buildings only
        buildings = {k: v for k, v in city_objects.items() 
                    if v.get('type', '').startswith('Building')}
        
        print(f"  Found {len(buildings)} building objects")
        
        if not buildings:
            print("  WARNING: No buildings found in CityJSON")
            return None
        
        # Collect all building geometry
        all_verts = []
        all_faces = []
        vert_offset = 0
        buildings_in_bounds = 0
        buildings_outside = 0
        
        for bldg_id, bldg_data in buildings.items():
            geometry = bldg_data.get('geometry', [])
            
            if not geometry:
                continue
            
            # Select appropriate LoD
            selected_geom = None
            if props.cityjson_use_lod == 'highest':
                # Find highest LoD
                best_lod = -1
                for geom in geometry:
                    lod = geom.get('lod', 0)
                    if isinstance(lod, str):
                        try:
                            lod = float(lod)
                        except:
                            lod = 0
                    if lod > best_lod:
                        best_lod = lod
                        selected_geom = geom
            else:
                # Find specific LoD
                target_lod = props.cityjson_use_lod
                for geom in geometry:
                    lod = str(geom.get('lod', '0'))
                    if lod == target_lod or lod.startswith(target_lod):
                        selected_geom = geom
                        break
                # Fallback to any geometry
                if not selected_geom and geometry:
                    selected_geom = geometry[0]
            
            if not selected_geom:
                continue
            
            # Extract boundaries (faces)
            boundaries = selected_geom.get('boundaries', [])
            geom_type = selected_geom.get('type', '')
            
            # Check if building is within terrain bounds (check first vertex)
            building_verts = set()
            self._collect_vertex_indices(boundaries, building_verts)
            
            if not building_verts:
                continue
            
            # Check bounds using first few vertices
            sample_verts = list(building_verts)[:10]
            in_bounds = False
            for vi in sample_verts:
                if vi < len(vertices):
                    vx, vy, vz = vertices[vi]
                    if terrain_min_x <= vx <= terrain_max_x and terrain_min_y <= vy <= terrain_max_y:
                        in_bounds = True
                        break
            
            if not in_bounds:
                buildings_outside += 1
                continue
            
            buildings_in_bounds += 1
            
            # Process geometry based on type
            faces = self._extract_cityjson_faces(boundaries, geom_type)
            
            # Add vertices and faces to combined mesh
            for face_indices in faces:
                new_face = []
                for vi in face_indices:
                    if vi < len(vertices):
                        vx, vy, vz = vertices[vi]
                        all_verts.append((vx, vy, vz))
                        new_face.append(vert_offset)
                        vert_offset += 1
                
                if len(new_face) >= 3:
                    all_faces.append(new_face)
        
        print(f"  Buildings in terrain bounds: {buildings_in_bounds}")
        print(f"  Buildings outside bounds: {buildings_outside}")
        print(f"  Total vertices collected: {len(all_verts):,}")
        print(f"  Total faces collected: {len(all_faces):,}")
        
        if not all_verts or not all_faces:
            print("  WARNING: No building geometry within terrain bounds")
            return None
        
        # Create mesh
        mesh = bpy.data.meshes.new("Buildings_CityJSON")
        
        # Create mesh from vertices and faces
        mesh.from_pydata(all_verts, [], all_faces)
        mesh.update()
        
        # Create object
        building_obj = bpy.data.objects.new("Buildings", mesh)
        context.collection.objects.link(building_obj)
        
        print(f"  Created mesh: {len(mesh.vertices):,} vertices, {len(mesh.polygons):,} faces")
        
        # Clean up mesh
        bpy.context.view_layer.objects.active = building_obj
        bpy.ops.object.select_all(action='DESELECT')
        building_obj.select_set(True)
        
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.remove_doubles(threshold=0.01)
        bpy.ops.mesh.normals_make_consistent(inside=False)
        bpy.ops.object.mode_set(mode='OBJECT')
        
        print(f"  After cleanup: {len(building_obj.data.vertices):,} vertices")
        
        # =====================================================================
        # Z ALIGNMENT: Adjust buildings to match actual terrain elevation
        # =====================================================================
        # The CityJSON buildings have Z values based on real-world elevation,
        # but there may be a systematic offset vs the BlenderGIS terrain.
        # We'll sample the terrain elevation at several building locations
        # and calculate the necessary Z offset.
        
        print(f"  Aligning buildings to terrain elevation...")
        
        # Get building Z range (before alignment)
        building_z_values = [v.co.z for v in building_obj.data.vertices]
        building_min_z = min(building_z_values)
        building_max_z = max(building_z_values)
        print(f"  Building Z range (before alignment): [{building_min_z:.1f}, {building_max_z:.1f}]")
        
        # Sample terrain elevation at building XY locations using raycasting
        # Import BVHTree for efficient raycasting
        from mathutils.bvhtree import BVHTree
        
        # Create BVH tree from terrain mesh for raycasting
        terrain_bvh = BVHTree.FromObject(dem_obj, context.evaluated_depsgraph_get())
        
        # Sample points: use the lowest vertices (likely ground floor)
        # Sort vertices by Z and take bottom 10% as ground floor candidates
        sorted_verts = sorted(enumerate(building_obj.data.vertices), key=lambda x: x[1].co.z)
        sample_count = max(10, len(sorted_verts) // 10)
        ground_floor_verts = sorted_verts[:sample_count]
        
        z_differences = []
        for idx, vert in ground_floor_verts:
            # Ray from high above downward
            ray_origin = Vector((vert.co.x, vert.co.y, terrain_max_z + 1000))
            ray_direction = Vector((0, 0, -1))
            
            # Cast ray to find terrain surface
            hit_location, hit_normal, hit_index, hit_distance = terrain_bvh.ray_cast(ray_origin, ray_direction)
            
            if hit_location:
                terrain_z_at_building = hit_location.z
                building_z = vert.co.z
                z_diff = terrain_z_at_building - building_z
                z_differences.append(z_diff)
        
        if z_differences:
            # Use median to avoid outliers
            z_differences.sort()
            median_idx = len(z_differences) // 2
            z_adjustment = z_differences[median_idx]
            
            print(f"  Terrain sampling: {len(z_differences)} points")
            print(f"  Z differences range: [{min(z_differences):.1f}, {max(z_differences):.1f}]")
            print(f"  Median Z adjustment needed: {z_adjustment:.1f}m")
            
            # Apply Z adjustment to all building vertices
            if abs(z_adjustment) > 0.5:  # Only adjust if significant
                print(f"  Applying Z adjustment: {z_adjustment:.1f}m")
                for vert in building_obj.data.vertices:
                    vert.co.z += z_adjustment
                building_obj.data.update()
                
                # Report new Z range
                building_z_values = [v.co.z for v in building_obj.data.vertices]
                building_min_z = min(building_z_values)
                building_max_z = max(building_z_values)
                print(f"  Building Z range (after alignment): [{building_min_z:.1f}, {building_max_z:.1f}]")
        else:
            print(f"  WARNING: Could not sample terrain elevation (no ray hits)")
        
        # Bisect at terrain boundaries
        print(f"  Cutting buildings at terrain boundaries...")
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        
        # Cut at all 4 edges
        bpy.ops.mesh.bisect(plane_co=(terrain_min_x, 0, 0), plane_no=(1, 0, 0), clear_inner=True, clear_outer=False)
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.bisect(plane_co=(terrain_max_x, 0, 0), plane_no=(-1, 0, 0), clear_inner=True, clear_outer=False)
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.bisect(plane_co=(0, terrain_min_y, 0), plane_no=(0, 1, 0), clear_inner=True, clear_outer=False)
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.bisect(plane_co=(0, terrain_max_y, 0), plane_no=(0, -1, 0), clear_inner=True, clear_outer=False)
        
        bpy.ops.object.mode_set(mode='OBJECT')
        
        # Extend buildings downward to ensure they intersect terrain
        print(f"  Extending buildings {props.building_depth}m below surface...")
        
        # Move buildings down by building_depth
        for vert in building_obj.data.vertices:
            vert.co.z -= props.building_depth
        
        building_obj.data.update()
        
        final_verts = len(building_obj.data.vertices)
        if final_verts == 0:
            print("  WARNING: No building geometry remaining after clipping")
            bpy.data.objects.remove(building_obj, do_unlink=True)
            return None
        
        print(f"✓ CityJSON buildings added: {final_verts:,} vertices")
        
        return building_obj
    
    def _collect_vertex_indices(self, boundaries, vertex_set):
        """Recursively collect all vertex indices from CityJSON boundaries"""
        if isinstance(boundaries, int):
            vertex_set.add(boundaries)
        elif isinstance(boundaries, list):
            for item in boundaries:
                self._collect_vertex_indices(item, vertex_set)
    
    def _extract_cityjson_faces(self, boundaries, geom_type):
        """Extract face lists from CityJSON boundaries based on geometry type"""
        faces = []
        
        if geom_type == 'MultiSurface' or geom_type == 'CompositeSurface':
            # boundaries is a list of surfaces, each surface is a list of rings
            for surface in boundaries:
                if isinstance(surface, list) and len(surface) > 0:
                    # First ring is exterior, rest are holes (ignore holes for now)
                    exterior = surface[0] if isinstance(surface[0], list) else surface
                    if len(exterior) >= 3:
                        faces.append(exterior)
        
        elif geom_type == 'Solid':
            # boundaries is a list of shells, first shell is exterior
            for shell in boundaries:
                if isinstance(shell, list):
                    for surface in shell:
                        if isinstance(surface, list) and len(surface) > 0:
                            exterior = surface[0] if isinstance(surface[0], list) else surface
                            if len(exterior) >= 3:
                                faces.append(exterior)
        
        elif geom_type == 'MultiSolid' or geom_type == 'CompositeSolid':
            # Multiple solids
            for solid in boundaries:
                if isinstance(solid, list):
                    for shell in solid:
                        if isinstance(shell, list):
                            for surface in shell:
                                if isinstance(surface, list) and len(surface) > 0:
                                    exterior = surface[0] if isinstance(surface[0], list) else surface
                                    if len(exterior) >= 3:
                                        faces.append(exterior)
        
        else:
            # Try to handle as generic nested list
            self._extract_faces_recursive(boundaries, faces)
        
        return faces
    
    def _extract_faces_recursive(self, data, faces):
        """Recursively extract faces from nested lists"""
        if not isinstance(data, list) or len(data) == 0:
            return
        
        # Check if this is a face (list of integers)
        if all(isinstance(x, int) for x in data):
            if len(data) >= 3:
                faces.append(data)
            return
        
        # Check if first element is a list of integers (surface with rings)
        if isinstance(data[0], list) and len(data[0]) > 0 and all(isinstance(x, int) for x in data[0]):
            if len(data[0]) >= 3:
                faces.append(data[0])  # exterior ring only
            return
        
        # Otherwise recurse
        for item in data:
            self._extract_faces_recursive(item, faces)
    
    def import_shapefile_direct(self, context, filepath):
        """Fallback: Import shapefile directly using pyshp without BlenderGIS"""
        try:
            import shapefile
        except ImportError:
            print("  pyshp not available for direct import")
            return False
        
        try:
            sf = shapefile.Reader(filepath)
            shapes = sf.shapes()
            
            if not shapes:
                print("  No shapes found in shapefile")
                return False
            
            print(f"  Reading {len(shapes)} shapes directly...")
            
            all_verts = []
            all_edges = []
            vert_offset = 0
            
            for shape in shapes:
                if shape.shapeType in [5, 15, 25]:  # Polygon types
                    points = shape.points
                    parts = list(shape.parts) + [len(points)]
                    
                    for i in range(len(parts) - 1):
                        start = parts[i]
                        end = parts[i + 1]
                        ring_points = points[start:end]
                        
                        for j, pt in enumerate(ring_points):
                            all_verts.append((pt[0], pt[1], 0))
                            if j > 0:
                                all_edges.append((vert_offset + j - 1, vert_offset + j))
                        # Close the ring
                        if len(ring_points) > 2:
                            all_edges.append((vert_offset + len(ring_points) - 1, vert_offset))
                        vert_offset += len(ring_points)
            
            if not all_verts:
                print("  No vertices extracted from shapefile")
                return False
            
            # Create mesh
            mesh = bpy.data.meshes.new("Buildings_Direct")
            mesh.from_pydata(all_verts, all_edges, [])
            mesh.update()
            
            obj = bpy.data.objects.new("Buildings", mesh)
            context.collection.objects.link(obj)
            
            print(f"  Direct import: {len(all_verts)} vertices, {len(all_edges)} edges")
            return True
            
        except Exception as e:
            print(f"  Direct shapefile read error: {e}")
            return False
    
    def add_roads(self, context, dem_obj, props):
        """Import roads from shapefile and project onto terrain
        
        Workflow matching manual process:
        1. Import shapefile as mesh (sparse line vertices)
        2. Subdivide to densify (6 levels simple)
        3. Lift above terrain and shrinkwrap
        4. Prune vertices that didn't shrinkwrap (still high)
        5. Convert to curve, add rectangular profile, convert back to mesh
        """
        print(f"  Importing roads from: {os.path.basename(props.road_shapefile)}")
        
        # Get terrain bounds BEFORE importing roads
        terrain_bbox = [dem_obj.matrix_world @ Vector(corner) for corner in dem_obj.bound_box]
        terrain_min_x = min(v.x for v in terrain_bbox)
        terrain_max_x = max(v.x for v in terrain_bbox)
        terrain_min_y = min(v.y for v in terrain_bbox)
        terrain_max_y = max(v.y for v in terrain_bbox)
        terrain_center_x = (terrain_min_x + terrain_max_x) / 2
        terrain_center_y = (terrain_min_y + terrain_max_y) / 2
        terrain_max_z = max((dem_obj.matrix_world @ v.co).z for v in dem_obj.data.vertices)
        terrain_min_z = min((dem_obj.matrix_world @ v.co).z for v in dem_obj.data.vertices)
        
        print(f"  Terrain center: ({terrain_center_x:.0f}, {terrain_center_y:.0f})")
        print(f"  Terrain bounds: X[{terrain_min_x:.0f}, {terrain_max_x:.0f}] Y[{terrain_min_y:.0f}, {terrain_max_y:.0f}]")
        
        before = set(context.scene.objects)
        imported = False
        
        # Try importing shapefile
        try:
            result = bpy.ops.importgis.shapefile(filepath=props.road_shapefile)
            if result == {'FINISHED'}:
                imported = True
        except Exception as e:
            print(f"  Standard import failed: {str(e)[:100]}")
        
        if not imported:
            print("  Attempting import with explicit CRS (EPSG:3857)...")
            try:
                result = bpy.ops.importgis.shapefile(
                    filepath=props.road_shapefile,
                    shpCRS='EPSG:3857',
                )
                if result == {'FINISHED'}:
                    imported = True
            except Exception as e:
                print(f"  EPSG:3857 import failed: {str(e)[:100]}")
        
        if not imported:
            print("  Attempting import with EPSG:4326 (WGS84)...")
            try:
                result = bpy.ops.importgis.shapefile(
                    filepath=props.road_shapefile,
                    shpCRS='EPSG:4326',
                )
                if result == {'FINISHED'}:
                    imported = True
            except Exception as e:
                print(f"  EPSG:4326 import failed: {str(e)[:100]}")
        
        if not imported:
            print("  ERROR: Could not import road shapefile")
            return None
        
        after = set(context.scene.objects)
        new_objs = list(after - before)
        
        if not new_objs:
            print("  No NEW objects imported from shapefile")
            return None
        
        road_obj = new_objs[0]
        road_obj.name = "Roads_Import"
        initial_verts = len(road_obj.data.vertices)
        print(f"  Imported {initial_verts:,} vertices")
        
        if initial_verts == 0:
            print("  WARNING: Road shapefile imported but has no vertices")
            bpy.data.objects.remove(road_obj, do_unlink=True)
            return None
        
        # Check road bounds
        road_bbox = [road_obj.matrix_world @ Vector(corner) for corner in road_obj.bound_box]
        road_min_x = min(v.x for v in road_bbox)
        road_max_x = max(v.x for v in road_bbox)
        road_min_y = min(v.y for v in road_bbox)
        road_max_y = max(v.y for v in road_bbox)
        print(f"  Road bounds: X[{road_min_x:.0f}, {road_max_x:.0f}] Y[{road_min_y:.0f}, {road_max_y:.0f}]")
        
        # Store original bounds for coordinate transformation in road labels
        road_obj["original_min_x"] = road_min_x
        road_obj["original_max_x"] = road_max_x
        road_obj["original_min_y"] = road_min_y
        road_obj["original_max_y"] = road_max_y
        
        # Note: We do NOT apply CRS offset - the shapefile covers a larger area
        # and shrinkwrap + pruning will extract just the portion over our terrain
        
        # Pre-prune: Remove vertices far outside terrain XY bounds BEFORE subdivision
        # But keep vertices that are part of edges crossing into the terrain
        margin = 500  # Larger margin to catch roads approaching terrain
        
        bpy.context.view_layer.objects.active = road_obj
        bpy.ops.object.select_all(action='DESELECT')
        road_obj.select_set(True)
        
        mesh = road_obj.data
        
        # First, identify which vertices are inside the extended bounds
        inside_bounds = set()
        for i, vert in enumerate(mesh.vertices):
            world_co = road_obj.matrix_world @ vert.co
            if (terrain_min_x - margin <= world_co.x <= terrain_max_x + margin and
                terrain_min_y - margin <= world_co.y <= terrain_max_y + margin):
                inside_bounds.add(i)
        
        # Now find vertices connected to inside vertices (keep these too)
        connected_to_inside = set(inside_bounds)
        for edge in mesh.edges:
            v0, v1 = edge.vertices
            if v0 in inside_bounds or v1 in inside_bounds:
                connected_to_inside.add(v0)
                connected_to_inside.add(v1)
        
        # Select vertices that are NOT connected to any inside vertex
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='DESELECT')
        bpy.ops.object.mode_set(mode='OBJECT')
        
        outside_verts = 0
        for i, vert in enumerate(mesh.vertices):
            if i not in connected_to_inside:
                vert.select = True
                outside_verts += 1
        
        if outside_verts > 0:
            print(f"  Pre-pruning {outside_verts:,} disconnected vertices outside terrain")
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.delete(type='VERT')
            bpy.ops.object.mode_set(mode='OBJECT')
            print(f"  After pre-prune: {len(road_obj.data.vertices):,} vertices")
        
        if len(road_obj.data.vertices) == 0:
            print("  WARNING: No road vertices within terrain bounds")
            bpy.data.objects.remove(road_obj, do_unlink=True)
            return None
        
        # Step 1: Subdivide to densify the sparse line mesh
        print(f"  Subdividing 6 levels to densify lines...")
        bpy.context.view_layer.objects.active = road_obj
        bpy.ops.object.select_all(action='DESELECT')
        road_obj.select_set(True)
        
        subsurf = road_obj.modifiers.new(name="Subdivide", type='SUBSURF')
        subsurf.subdivision_type = 'SIMPLE'
        subsurf.levels = 6
        subsurf.render_levels = 6
        bpy.ops.object.modifier_apply(modifier=subsurf.name)
        
        print(f"  After subdivision: {len(road_obj.data.vertices):,} vertices")
        
        # Step 2: Lift above terrain
        lift_height = terrain_max_z + 500
        road_obj.location.z = lift_height
        bpy.ops.object.transform_apply(location=True)
        print(f"  Lifted to Z={lift_height:.0f}m")
        
        # Step 3: Shrinkwrap to terrain
        shrinkwrap = road_obj.modifiers.new(name="Shrinkwrap", type='SHRINKWRAP')
        shrinkwrap.target = dem_obj
        shrinkwrap.wrap_method = 'PROJECT'
        shrinkwrap.use_project_z = True
        shrinkwrap.use_negative_direction = True
        shrinkwrap.use_positive_direction = False
        
        bpy.ops.object.modifier_apply(modifier=shrinkwrap.name)
        print(f"  Shrinkwrap applied")
        
        # Step 4: Prune vertices that didn't shrinkwrap (still above terrain)
        threshold_z = terrain_max_z + 100
        
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='DESELECT')
        bpy.ops.object.mode_set(mode='OBJECT')
        
        mesh = road_obj.data
        high_verts = 0
        for vert in mesh.vertices:
            world_co = road_obj.matrix_world @ vert.co
            if world_co.z > threshold_z:
                vert.select = True
                high_verts += 1
        
        if high_verts > 0:
            print(f"  Found {high_verts:,} vertices that didn't shrinkwrap")
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.delete(type='VERT')
            bpy.ops.object.mode_set(mode='OBJECT')
        
        remaining_verts = len(road_obj.data.vertices)
        print(f"  After pruning: {remaining_verts:,} vertices")
        
        if remaining_verts == 0:
            print("  WARNING: No road vertices remaining")
            bpy.data.objects.remove(road_obj, do_unlink=True)
            return None
        
        # Step 5: Convert to curve, add profile, convert back
        print(f"  Converting to curve for profile extrusion...")
        
        # IMPORTANT: Preserve original bounds before curve conversion destroys the object
        # These are needed for road label coordinate mapping
        preserved_bounds = {
            "original_min_x": road_obj.get("original_min_x"),
            "original_max_x": road_obj.get("original_max_x"),
            "original_min_y": road_obj.get("original_min_y"),
            "original_max_y": road_obj.get("original_max_y"),
        }
        
        bpy.context.view_layer.objects.active = road_obj
        bpy.ops.object.select_all(action='DESELECT')
        road_obj.select_set(True)
        bpy.ops.object.convert(target='CURVE')
        
        road_curve = bpy.context.active_object
        
        # Create rectangular profile
        half_width = props.road_width / 2
        half_height = (props.road_height + props.road_depth) / 2
        
        curve_data = bpy.data.curves.new('Road_Profile', type='CURVE')
        curve_data.dimensions = '2D'
        
        polyline = curve_data.splines.new('POLY')
        polyline.points.add(3)  # 4 points for rectangle
        polyline.points[0].co = (-half_width, -half_height, 0, 1)
        polyline.points[1].co = (half_width, -half_height, 0, 1)
        polyline.points[2].co = (half_width, half_height, 0, 1)
        polyline.points[3].co = (-half_width, half_height, 0, 1)
        polyline.use_cyclic_u = True
        
        bevel_obj = bpy.data.objects.new('Road_Profile', curve_data)
        context.collection.objects.link(bevel_obj)
        
        road_curve.data.bevel_mode = 'OBJECT'
        road_curve.data.bevel_object = bevel_obj
        road_curve.data.use_fill_caps = True
        print(f"  Applied {props.road_width}m x {props.road_height + props.road_depth}m profile")
        
        # Convert back to mesh
        bpy.ops.object.select_all(action='DESELECT')
        road_curve.select_set(True)
        bpy.context.view_layer.objects.active = road_curve
        bpy.ops.object.convert(target='MESH')
        road_obj = bpy.context.active_object
        road_obj.name = "Roads"
        
        # Restore preserved bounds for road label coordinate mapping
        for key, value in preserved_bounds.items():
            if value is not None:
                road_obj[key] = value
        
        # Clean up bevel object
        bpy.data.objects.remove(bevel_obj, do_unlink=True)
        
        print(f"  Converted to mesh: {len(road_obj.data.vertices):,} vertices")
        
        # Position so road_height is above terrain, road_depth below
        road_obj.location.z = props.road_height - half_height
        bpy.ops.object.transform_apply(location=True)
        
        # Final cleanup
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='DESELECT')
        bpy.ops.object.mode_set(mode='OBJECT')
        
        expected_min_z = terrain_min_z - props.road_depth - 100
        expected_max_z = terrain_max_z + props.road_height + 100
        
        mesh = road_obj.data
        stray_verts = 0
        for vert in mesh.vertices:
            world_co = road_obj.matrix_world @ vert.co
            if world_co.z < expected_min_z or world_co.z > expected_max_z:
                vert.select = True
                stray_verts += 1
        
        if stray_verts > 0:
            print(f"  Removing {stray_verts:,} stray vertices")
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.delete(type='VERT')
            bpy.ops.object.mode_set(mode='OBJECT')
        
        # Bisect on all 4 sides to cleanly cut roads at terrain boundary
        print(f"  Cutting roads at terrain boundaries...")
        bpy.context.view_layer.objects.active = road_obj
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        
        # Cut at min X (West edge) - plane normal points +X, cut everything below
        bpy.ops.mesh.bisect(
            plane_co=(terrain_min_x, 0, 0),
            plane_no=(1, 0, 0),
            clear_inner=True,
            clear_outer=False
        )
        bpy.ops.mesh.select_all(action='SELECT')
        
        # Cut at max X (East edge) - plane normal points -X, cut everything above
        bpy.ops.mesh.bisect(
            plane_co=(terrain_max_x, 0, 0),
            plane_no=(-1, 0, 0),
            clear_inner=True,
            clear_outer=False
        )
        bpy.ops.mesh.select_all(action='SELECT')
        
        # Cut at min Y (South edge) - plane normal points +Y
        bpy.ops.mesh.bisect(
            plane_co=(0, terrain_min_y, 0),
            plane_no=(0, 1, 0),
            clear_inner=True,
            clear_outer=False
        )
        bpy.ops.mesh.select_all(action='SELECT')
        
        # Cut at max Y (North edge) - plane normal points -Y
        bpy.ops.mesh.bisect(
            plane_co=(0, terrain_max_y, 0),
            plane_no=(0, -1, 0),
            clear_inner=True,
            clear_outer=False
        )
        
        bpy.ops.object.mode_set(mode='OBJECT')
        print(f"  After boundary cuts: {len(road_obj.data.vertices):,} vertices")
        
        print(f"✓ Roads added: {len(road_obj.data.vertices):,} vertices")
        
        return road_obj
    
    def add_trails(self, context, dem_obj, props):
        """Import trails from shapefile and project onto terrain
        
        Workflow matching manual process:
        1. Import shapefile as mesh (sparse line vertices)
        2. Subdivide to densify (6 levels simple)
        3. Lift above terrain and shrinkwrap
        4. Prune vertices that didn't shrinkwrap (still high)
        5. Convert to curve, add rectangular profile, convert back to mesh
        """
        print(f"  Importing trails from: {os.path.basename(props.trail_shapefile)}")
        
        # Get terrain bounds BEFORE importing
        terrain_bbox = [dem_obj.matrix_world @ Vector(corner) for corner in dem_obj.bound_box]
        terrain_min_x = min(v.x for v in terrain_bbox)
        terrain_max_x = max(v.x for v in terrain_bbox)
        terrain_min_y = min(v.y for v in terrain_bbox)
        terrain_max_y = max(v.y for v in terrain_bbox)
        terrain_center_x = (terrain_min_x + terrain_max_x) / 2
        terrain_center_y = (terrain_min_y + terrain_max_y) / 2
        terrain_max_z = max((dem_obj.matrix_world @ v.co).z for v in dem_obj.data.vertices)
        terrain_min_z = min((dem_obj.matrix_world @ v.co).z for v in dem_obj.data.vertices)
        
        print(f"  Terrain center: ({terrain_center_x:.0f}, {terrain_center_y:.0f})")
        print(f"  Terrain bounds: X[{terrain_min_x:.0f}, {terrain_max_x:.0f}] Y[{terrain_min_y:.0f}, {terrain_max_y:.0f}]")
        
        before = set(context.scene.objects)
        imported = False
        
        # Try importing shapefile
        try:
            result = bpy.ops.importgis.shapefile(filepath=props.trail_shapefile)
            if result == {'FINISHED'}:
                imported = True
        except Exception as e:
            print(f"  Standard import failed: {str(e)[:100]}")
        
        if not imported:
            print("  Attempting import with explicit CRS (EPSG:3857)...")
            try:
                result = bpy.ops.importgis.shapefile(
                    filepath=props.trail_shapefile,
                    shpCRS='EPSG:3857',
                )
                if result == {'FINISHED'}:
                    imported = True
            except Exception as e:
                print(f"  EPSG:3857 import failed: {str(e)[:100]}")
        
        if not imported:
            print("  Attempting import with EPSG:4326 (WGS84)...")
            try:
                result = bpy.ops.importgis.shapefile(
                    filepath=props.trail_shapefile,
                    shpCRS='EPSG:4326',
                )
                if result == {'FINISHED'}:
                    imported = True
            except Exception as e:
                print(f"  EPSG:4326 import failed: {str(e)[:100]}")
        
        if not imported:
            print("  ERROR: Could not import trail shapefile")
            return None
        
        after = set(context.scene.objects)
        new_objs = list(after - before)
        
        if not new_objs:
            print("  No NEW objects imported from shapefile")
            return None
        
        trail_obj = new_objs[0]
        trail_obj.name = "Trails_Import"
        initial_verts = len(trail_obj.data.vertices)
        print(f"  Imported {initial_verts:,} vertices")
        
        if initial_verts == 0:
            print("  WARNING: Trail shapefile imported but has no vertices")
            bpy.data.objects.remove(trail_obj, do_unlink=True)
            return None
        
        # Check trail bounds
        trail_bbox = [trail_obj.matrix_world @ Vector(corner) for corner in trail_obj.bound_box]
        trail_min_x = min(v.x for v in trail_bbox)
        trail_max_x = max(v.x for v in trail_bbox)
        trail_min_y = min(v.y for v in trail_bbox)
        trail_max_y = max(v.y for v in trail_bbox)
        print(f"  Trail bounds: X[{trail_min_x:.0f}, {trail_max_x:.0f}] Y[{trail_min_y:.0f}, {trail_max_y:.0f}]")
        
        # Note: We do NOT apply CRS offset - the shapefile covers a larger area
        # and shrinkwrap + pruning will extract just the portion over our terrain
        
        # Pre-prune: Remove vertices far outside terrain XY bounds BEFORE subdivision
        # But keep vertices that are part of edges crossing into the terrain
        margin = 500  # Larger margin to catch trails approaching terrain
        
        bpy.context.view_layer.objects.active = trail_obj
        bpy.ops.object.select_all(action='DESELECT')
        trail_obj.select_set(True)
        
        mesh = trail_obj.data
        
        # First, identify which vertices are inside the extended bounds
        inside_bounds = set()
        for i, vert in enumerate(mesh.vertices):
            world_co = trail_obj.matrix_world @ vert.co
            if (terrain_min_x - margin <= world_co.x <= terrain_max_x + margin and
                terrain_min_y - margin <= world_co.y <= terrain_max_y + margin):
                inside_bounds.add(i)
        
        # Now find vertices connected to inside vertices (keep these too)
        connected_to_inside = set(inside_bounds)
        for edge in mesh.edges:
            v0, v1 = edge.vertices
            if v0 in inside_bounds or v1 in inside_bounds:
                connected_to_inside.add(v0)
                connected_to_inside.add(v1)
        
        # Select vertices that are NOT connected to any inside vertex
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='DESELECT')
        bpy.ops.object.mode_set(mode='OBJECT')
        
        outside_verts = 0
        for i, vert in enumerate(mesh.vertices):
            if i not in connected_to_inside:
                vert.select = True
                outside_verts += 1
        
        if outside_verts > 0:
            print(f"  Pre-pruning {outside_verts:,} disconnected vertices outside terrain")
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.delete(type='VERT')
            bpy.ops.object.mode_set(mode='OBJECT')
            print(f"  After pre-prune: {len(trail_obj.data.vertices):,} vertices")
        
        if len(trail_obj.data.vertices) == 0:
            print("  WARNING: No trail vertices within terrain bounds")
            bpy.data.objects.remove(trail_obj, do_unlink=True)
            return None
        
        # Step 1: Subdivide to densify the sparse line mesh
        print(f"  Subdividing 6 levels to densify lines...")
        bpy.context.view_layer.objects.active = trail_obj
        bpy.ops.object.select_all(action='DESELECT')
        trail_obj.select_set(True)
        
        subsurf = trail_obj.modifiers.new(name="Subdivide", type='SUBSURF')
        subsurf.subdivision_type = 'SIMPLE'
        subsurf.levels = 6
        subsurf.render_levels = 6
        bpy.ops.object.modifier_apply(modifier=subsurf.name)
        
        print(f"  After subdivision: {len(trail_obj.data.vertices):,} vertices")
        
        # Step 2: Lift above terrain
        lift_height = terrain_max_z + 500
        trail_obj.location.z = lift_height
        bpy.ops.object.transform_apply(location=True)
        print(f"  Lifted to Z={lift_height:.0f}m")
        
        # Step 3: Shrinkwrap to terrain
        shrinkwrap = trail_obj.modifiers.new(name="Shrinkwrap", type='SHRINKWRAP')
        shrinkwrap.target = dem_obj
        shrinkwrap.wrap_method = 'PROJECT'
        shrinkwrap.use_project_z = True
        shrinkwrap.use_negative_direction = True
        shrinkwrap.use_positive_direction = False
        
        bpy.ops.object.modifier_apply(modifier=shrinkwrap.name)
        print(f"  Shrinkwrap applied")
        
        # Step 4: Prune vertices that didn't shrinkwrap
        threshold_z = terrain_max_z + 100
        
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='DESELECT')
        bpy.ops.object.mode_set(mode='OBJECT')
        
        mesh = trail_obj.data
        high_verts = 0
        for vert in mesh.vertices:
            world_co = trail_obj.matrix_world @ vert.co
            if world_co.z > threshold_z:
                vert.select = True
                high_verts += 1
        
        if high_verts > 0:
            print(f"  Found {high_verts:,} vertices that didn't shrinkwrap")
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.delete(type='VERT')
            bpy.ops.object.mode_set(mode='OBJECT')
        
        remaining_verts = len(trail_obj.data.vertices)
        print(f"  After pruning: {remaining_verts:,} vertices")
        
        if remaining_verts == 0:
            print("  WARNING: No trail vertices remaining")
            bpy.data.objects.remove(trail_obj, do_unlink=True)
            return None
        
        # Step 5: Convert to curve, add profile, convert back
        print(f"  Converting to curve for profile extrusion...")
        bpy.context.view_layer.objects.active = trail_obj
        bpy.ops.object.select_all(action='DESELECT')
        trail_obj.select_set(True)
        bpy.ops.object.convert(target='CURVE')
        
        trail_curve = bpy.context.active_object
        
        # Create rectangular profile
        half_width = props.trail_width / 2
        half_height = (props.trail_height + props.trail_depth) / 2
        
        curve_data = bpy.data.curves.new('Trail_Profile', type='CURVE')
        curve_data.dimensions = '2D'
        
        polyline = curve_data.splines.new('POLY')
        polyline.points.add(3)  # 4 points for rectangle
        polyline.points[0].co = (-half_width, -half_height, 0, 1)
        polyline.points[1].co = (half_width, -half_height, 0, 1)
        polyline.points[2].co = (half_width, half_height, 0, 1)
        polyline.points[3].co = (-half_width, half_height, 0, 1)
        polyline.use_cyclic_u = True
        
        bevel_obj = bpy.data.objects.new('Trail_Profile', curve_data)
        context.collection.objects.link(bevel_obj)
        
        trail_curve.data.bevel_mode = 'OBJECT'
        trail_curve.data.bevel_object = bevel_obj
        trail_curve.data.use_fill_caps = True
        print(f"  Applied {props.trail_width}m x {props.trail_height + props.trail_depth}m profile")
        
        # Convert back to mesh
        bpy.ops.object.select_all(action='DESELECT')
        trail_curve.select_set(True)
        bpy.context.view_layer.objects.active = trail_curve
        bpy.ops.object.convert(target='MESH')
        trail_obj = bpy.context.active_object
        trail_obj.name = "Trails"
        
        # Clean up bevel object
        bpy.data.objects.remove(bevel_obj, do_unlink=True)
        
        print(f"  Converted to mesh: {len(trail_obj.data.vertices):,} vertices")
        
        # Position so trail_height is above terrain, trail_depth below
        trail_obj.location.z = props.trail_height - half_height
        bpy.ops.object.transform_apply(location=True)
        
        # Final cleanup
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='DESELECT')
        bpy.ops.object.mode_set(mode='OBJECT')
        
        expected_min_z = terrain_min_z - props.trail_depth - 100
        expected_max_z = terrain_max_z + props.trail_height + 100
        
        mesh = trail_obj.data
        stray_verts = 0
        for vert in mesh.vertices:
            world_co = trail_obj.matrix_world @ vert.co
            if world_co.z < expected_min_z or world_co.z > expected_max_z:
                vert.select = True
                stray_verts += 1
        
        if stray_verts > 0:
            print(f"  Removing {stray_verts:,} stray vertices")
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.delete(type='VERT')
            bpy.ops.object.mode_set(mode='OBJECT')
        
        # Bisect on all 4 sides to cleanly cut trails at terrain boundary
        print(f"  Cutting trails at terrain boundaries...")
        bpy.context.view_layer.objects.active = trail_obj
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        
        # Cut at min X (West edge)
        bpy.ops.mesh.bisect(
            plane_co=(terrain_min_x, 0, 0),
            plane_no=(1, 0, 0),
            clear_inner=True,
            clear_outer=False
        )
        bpy.ops.mesh.select_all(action='SELECT')
        
        # Cut at max X (East edge)
        bpy.ops.mesh.bisect(
            plane_co=(terrain_max_x, 0, 0),
            plane_no=(-1, 0, 0),
            clear_inner=True,
            clear_outer=False
        )
        bpy.ops.mesh.select_all(action='SELECT')
        
        # Cut at min Y (South edge)
        bpy.ops.mesh.bisect(
            plane_co=(0, terrain_min_y, 0),
            plane_no=(0, 1, 0),
            clear_inner=True,
            clear_outer=False
        )
        bpy.ops.mesh.select_all(action='SELECT')
        
        # Cut at max Y (North edge)
        bpy.ops.mesh.bisect(
            plane_co=(0, terrain_max_y, 0),
            plane_no=(0, -1, 0),
            clear_inner=True,
            clear_outer=False
        )
        
        bpy.ops.object.mode_set(mode='OBJECT')
        print(f"  After boundary cuts: {len(trail_obj.data.vertices):,} vertices")
        
        print(f"✓ Trails added: {len(trail_obj.data.vertices):,} vertices")
        
        return trail_obj
    
    def add_road_labels(self, context, dem_obj, road_obj, props):
        """Generate street name labels as separate meshes that extrude DOWN through roads
        
        Strategy: Extract road centerlines from the actual road mesh in Blender,
        then match each centerline segment to a road name from the shapefile.
        Labels are created extruding downward for multi-color 3D printing.
        """
        import math
        print(f"  Generating road labels...")
        
        if road_obj is None:
            print("  ERROR: No road object available")
            return None
        
        try:
            import shapefile
        except ImportError:
            print("  ERROR: pyshp not installed, cannot read road names")
            return None
        
        # Get terrain info
        terrain_bbox = [dem_obj.matrix_world @ Vector(corner) for corner in dem_obj.bound_box]
        terrain_min_x = min(v.x for v in terrain_bbox)
        terrain_max_x = max(v.x for v in terrain_bbox)
        terrain_min_y = min(v.y for v in terrain_bbox)
        terrain_max_y = max(v.y for v in terrain_bbox)
        terrain_max_z = max((dem_obj.matrix_world @ v.co).z for v in dem_obj.data.vertices)
        terrain_min_z = min((dem_obj.matrix_world @ v.co).z for v in dem_obj.data.vertices)
        
        print(f"  Terrain bounds: X[{terrain_min_x:.0f}, {terrain_max_x:.0f}] Y[{terrain_min_y:.0f}, {terrain_max_y:.0f}]")
        
        # Read shapefile for names
        try:
            shp_path = props.road_shapefile
            if shp_path.lower().endswith('.shp'):
                shp_base = shp_path[:-4]
            else:
                shp_base = shp_path
            
            dbf_path = shp_base + '.dbf'
            if not os.path.exists(dbf_path):
                alt_base = shp_base.replace(' ', '_')
                if os.path.exists(alt_base + '.dbf'):
                    shp_base = alt_base
                else:
                    print(f"  ERROR: Cannot find .dbf file at {dbf_path}")
                    return None
            
            sf = shapefile.Reader(shp_base)
            print(f"  Reading names from: {shp_base}")
        except Exception as e:
            print(f"  ERROR: Cannot read shapefile: {e}")
            return None
        
        fields = [f[0] for f in sf.fields[1:]]
        name_field_idx = None
        for i, f in enumerate(fields):
            if f.lower() == 'name':
                name_field_idx = i
                break
        
        if name_field_idx is None:
            print("  ERROR: No 'name' field found in shapefile")
            return None
        
        shapes = sf.shapes()
        records = sf.records()
        
        # Get ALL shapefile points to determine bounds
        all_shp_points = []
        for shape in shapes:
            all_shp_points.extend(shape.points)
        
        if not all_shp_points:
            print("  ERROR: No points in shapefile")
            return None
        
        shp_min_x = min(p[0] for p in all_shp_points)
        shp_max_x = max(p[0] for p in all_shp_points)
        shp_min_y = min(p[1] for p in all_shp_points)
        shp_max_y = max(p[1] for p in all_shp_points)
        
        print(f"  Shapefile bounds: X[{shp_min_x:.0f}, {shp_max_x:.0f}] Y[{shp_min_y:.0f}, {shp_max_y:.0f}]")
        
        # Get the ORIGINAL road bounds that were stored during import
        # These represent where BlenderGIS placed the full shapefile data in Blender coordinates
        # The shapefile covers multiple tiles, so we need to match shapefile min to Blender min
        if road_obj is not None and "original_min_x" in road_obj:
            orig_road_min_x = road_obj["original_min_x"]
            orig_road_max_x = road_obj["original_max_x"]
            orig_road_min_y = road_obj["original_min_y"]
            orig_road_max_y = road_obj["original_max_y"]
            print(f"  Original road Blender bounds: X[{orig_road_min_x:.0f}, {orig_road_max_x:.0f}] Y[{orig_road_min_y:.0f}, {orig_road_max_y:.0f}]")
        else:
            # Fallback: use current road bounds (less accurate after pruning)
            if road_obj is not None:
                road_bbox = [road_obj.matrix_world @ Vector(corner) for corner in road_obj.bound_box]
                orig_road_min_x = min(v.x for v in road_bbox)
                orig_road_max_x = max(v.x for v in road_bbox)
                orig_road_min_y = min(v.y for v in road_bbox)
                orig_road_max_y = max(v.y for v in road_bbox)
                print(f"  Road Blender bounds (current, fallback): X[{orig_road_min_x:.0f}, {orig_road_max_x:.0f}] Y[{orig_road_min_y:.0f}, {orig_road_max_y:.0f}]")
            else:
                print("  ERROR: No road object and no stored bounds")
                return None
        
        # Calculate offset: blender_coord = shapefile_coord - offset
        # The shapefile min corner maps to the Blender min corner (where BlenderGIS placed it)
        # So: orig_road_min = shp_min - offset  →  offset = shp_min - orig_road_min
        offset_x = shp_min_x - orig_road_min_x
        offset_y = shp_min_y - orig_road_min_y
        
        print(f"  Coordinate offset: ({offset_x:.0f}, {offset_y:.0f})")
        
        # Build list of named roads with their geometry in BLENDER coordinates
        named_roads = []
        for shape, record in zip(shapes, records):
            name = record[name_field_idx]
            if not name or not str(name).strip():
                continue
            
            name = str(name).strip()
            points = shape.points
            if len(points) < 2:
                continue
            
            # Convert all points to Blender coordinates
            # blender_coord = shapefile_coord - offset
            blender_points = [(p[0] - offset_x, p[1] - offset_y) for p in points]
            
            # Check if any part of this road is within terrain bounds (with margin)
            margin = 100  # meters
            has_inside = False
            for bp in blender_points:
                if (terrain_min_x - margin <= bp[0] <= terrain_max_x + margin and
                    terrain_min_y - margin <= bp[1] <= terrain_max_y + margin):
                    has_inside = True
                    break
            
            # Also check if segments cross the terrain
            if not has_inside:
                for i in range(len(blender_points) - 1):
                    p1, p2 = blender_points[i], blender_points[i+1]
                    seg_min_x, seg_max_x = min(p1[0], p2[0]), max(p1[0], p2[0])
                    seg_min_y, seg_max_y = min(p1[1], p2[1]), max(p1[1], p2[1])
                    if (seg_min_x <= terrain_max_x + margin and seg_max_x >= terrain_min_x - margin and
                        seg_min_y <= terrain_max_y + margin and seg_max_y >= terrain_min_y - margin):
                        has_inside = True
                        break
            
            if has_inside:
                named_roads.append((name, blender_points))
        
        print(f"  Found {len(named_roads)} named roads potentially intersecting terrain")
        
        if not named_roads:
            print("  WARNING: No named roads found in terrain area")
            print("  This may indicate a coordinate system mismatch")
            return None
        
        # For each named road, find the midpoint of the portion inside the terrain
        labeled_roads = []
        seen_names = set()
        
        for name, blender_points in named_roads:
            if name in seen_names:
                continue
            
            # Find segments inside terrain and calculate midpoint
            inside_segments = []
            for i in range(len(blender_points) - 1):
                p1, p2 = blender_points[i], blender_points[i+1]
                
                p1_inside = (terrain_min_x <= p1[0] <= terrain_max_x and
                            terrain_min_y <= p1[1] <= terrain_max_y)
                p2_inside = (terrain_min_x <= p2[0] <= terrain_max_x and
                            terrain_min_y <= p2[1] <= terrain_max_y)
                
                if p1_inside or p2_inside:
                    inside_segments.append((p1, p2))
                else:
                    # Check crossing
                    seg_min_x, seg_max_x = min(p1[0], p2[0]), max(p1[0], p2[0])
                    seg_min_y, seg_max_y = min(p1[1], p2[1]), max(p1[1], p2[1])
                    if (seg_min_x <= terrain_max_x and seg_max_x >= terrain_min_x and
                        seg_min_y <= terrain_max_y and seg_max_y >= terrain_min_y):
                        inside_segments.append((p1, p2))
            
            if not inside_segments:
                continue
            
            # Calculate total length
            inside_length = sum(
                ((seg[1][0] - seg[0][0])**2 + (seg[1][1] - seg[0][1])**2)**0.5
                for seg in inside_segments
            )
            
            if inside_length < props.road_label_min_length:
                continue
            
            # Find midpoint
            target_dist = inside_length / 2
            current_dist = 0
            mid_x, mid_y = inside_segments[0][0]
            angle = 0
            
            for seg in inside_segments:
                p1, p2 = seg
                seg_len = ((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2)**0.5
                
                if current_dist + seg_len >= target_dist:
                    t = (target_dist - current_dist) / seg_len if seg_len > 0 else 0
                    mid_x = p1[0] + t * (p2[0] - p1[0])
                    mid_y = p1[1] + t * (p2[1] - p1[1])
                    angle = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
                    break
                current_dist += seg_len
            
            # Abbreviate name first to get accurate length estimate
            abbrev_name = name
            for full, abbr in [(' Street', ' St'), (' Avenue', ' Ave'), (' Boulevard', ' Blvd'),
                              (' Drive', ' Dr'), (' Road', ' Rd'), (' Lane', ' Ln'),
                              (' Court', ' Ct'), (' Place', ' Pl'), (' Circle', ' Cir'),
                              (' Trail', ' Tr'), (' Way', ' Wy'), (' Heights', ' Hts')]:
                if abbrev_name.endswith(full):
                    abbrev_name = abbrev_name[:-len(full)] + abbr
                    break
            
            # Estimate label dimensions
            # Text width is roughly 0.6 * size * num_characters
            # Text height is roughly 0.8 * size
            est_label_width = len(abbrev_name) * props.road_label_size * 0.6
            est_label_height = props.road_label_size * 0.8
            
            # Make sure angle results in left-to-right readable text
            label_angle = angle
            if label_angle > math.pi / 2 or label_angle < -math.pi / 2:
                label_angle = label_angle + math.pi
            
            # Calculate the four corners of the label bounding box
            # relative to center point, considering rotation
            half_w = est_label_width / 2
            half_h = est_label_height / 2
            cos_a = math.cos(label_angle)
            sin_a = math.sin(label_angle)
            
            # Four corners relative to center
            corners = [
                (-half_w * cos_a - half_h * sin_a + mid_x, -half_w * sin_a + half_h * cos_a + mid_y),
                ( half_w * cos_a - half_h * sin_a + mid_x,  half_w * sin_a + half_h * cos_a + mid_y),
                ( half_w * cos_a + half_h * sin_a + mid_x,  half_w * sin_a - half_h * cos_a + mid_y),
                (-half_w * cos_a + half_h * sin_a + mid_x, -half_w * sin_a - half_h * cos_a + mid_y),
            ]
            
            # Check if ALL corners are inside terrain bounds with margin
            margin = props.road_label_size * 0.5  # Small margin from edge
            all_inside = True
            for cx, cy in corners:
                if (cx < terrain_min_x + margin or cx > terrain_max_x - margin or
                    cy < terrain_min_y + margin or cy > terrain_max_y - margin):
                    all_inside = False
                    break
            
            if not all_inside:
                # Label would extend outside tile - skip this road
                continue
            
            labeled_roads.append((name, mid_x, mid_y, angle, inside_length))
            seen_names.add(name)
        
        print(f"  Found {len(labeled_roads)} roads to label")
        
        if not labeled_roads:
            return None
        
        # Abbreviate common road name suffixes
        abbreviations = {
            ' Street': ' St',
            ' Avenue': ' Ave',
            ' Boulevard': ' Blvd',
            ' Drive': ' Dr',
            ' Road': ' Rd',
            ' Lane': ' Ln',
            ' Court': ' Ct',
            ' Place': ' Pl',
            ' Circle': ' Cir',
            ' Trail': ' Tr',
            ' Way': ' Wy',
            ' Terrace': ' Ter',
            ' Highway': ' Hwy',
            ' Parkway': ' Pkwy',
            ' Heights': ' Hts',
            ' Point': ' Pt',
            ' Square': ' Sq',
            ' North': ' N',
            ' South': ' S',
            ' East': ' E',
            ' West': ' W',
        }
        
        def abbreviate_name(name):
            for full, abbrev in abbreviations.items():
                if name.endswith(full):
                    name = name[:-len(full)] + abbrev
                    break
            return name
        
        # Filter out overlapping labels
        min_distance = props.road_label_size * 3  # Minimum distance between labels
        filtered_roads = []
        
        for name, x, y, angle, length in labeled_roads:
            # Check distance to all already-added labels
            too_close = False
            for _, ox, oy, _, _ in filtered_roads:
                dist = ((x - ox)**2 + (y - oy)**2)**0.5
                if dist < min_distance:
                    too_close = True
                    break
            
            if not too_close:
                filtered_roads.append((name, x, y, angle, length))
        
        print(f"  After overlap filtering: {len(filtered_roads)} labels")
        
        if not filtered_roads:
            return None
        
        # Calculate how deep labels need to go to penetrate through roads
        # Labels should go from above road surface down through the road depth
        total_label_depth = props.road_height + props.road_depth + props.road_label_height
        
        print(f"  Label extrusion: {total_label_depth:.1f}m total depth (through road)")
        
        # Create text objects for each label
        # Strategy: Create 2D text, shrinkwrap to terrain, THEN solidify downward
        # This makes labels follow terrain contours while maintaining thickness
        label_objects = []
        
        for name, x, y, angle, length in filtered_roads:
            # Abbreviate the name
            abbrev_name = abbreviate_name(name)
            
            # Create text high above terrain (will be shrinkwrapped down)
            # NO extrusion yet - we'll add thickness after shrinkwrap
            bpy.ops.object.text_add(location=(x, y, terrain_max_z + 500))
            text_obj = context.active_object
            text_obj.data.body = abbrev_name
            text_obj.data.size = props.road_label_size
            text_obj.data.align_x = 'CENTER'
            text_obj.data.align_y = 'CENTER'
            text_obj.data.extrude = 0  # No extrusion - just 2D text
            
            # Rotate around Z to align with road direction
            # Make sure text reads left-to-right (flip if pointing left)
            road_angle = angle
            if road_angle > math.pi / 2 or road_angle < -math.pi / 2:
                road_angle = road_angle + math.pi
            text_obj.rotation_euler = (0, 0, road_angle)
            
            # Convert to mesh (still 2D at this point)
            bpy.ops.object.convert(target='MESH')
            mesh_obj = context.active_object
            
            # Shrinkwrap to terrain - this makes the 2D text follow terrain contours
            shrinkwrap = mesh_obj.modifiers.new(name="Shrinkwrap", type='SHRINKWRAP')
            shrinkwrap.target = dem_obj
            shrinkwrap.wrap_method = 'PROJECT'
            shrinkwrap.use_project_z = True
            shrinkwrap.use_negative_direction = True
            shrinkwrap.use_positive_direction = False
            shrinkwrap.offset = props.road_height + 0.5  # Place at road surface height
            
            bpy.ops.object.modifier_apply(modifier=shrinkwrap.name)
            
            # NOW add thickness by extruding in edit mode
            # This is cleaner than Solidify for text meshes
            bpy.context.view_layer.objects.active = mesh_obj
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            
            # Extrude downward
            bpy.ops.mesh.extrude_region_move(
                TRANSFORM_OT_translate={"value": (0, 0, -total_label_depth)}
            )
            
            # Clean up - merge any duplicate vertices
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.remove_doubles(threshold=0.1)
            
            bpy.ops.object.mode_set(mode='OBJECT')
            
            # Raise the label so top surface is slightly above road surface
            # The shrinkwrap placed the text AT road surface level
            # Move up so there's a small gap above the road
            label_raise = 1.5  # meters above road surface
            mesh_obj.location.z += label_raise
            
            # Apply transforms
            bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
            
            label_objects.append(mesh_obj)
            print(f"    Label: '{abbrev_name}' at ({x:.0f}, {y:.0f})")
        
        if not label_objects:
            return None
        
        # Join all labels into one object (they're already shrinkwrapped individually)
        bpy.ops.object.select_all(action='DESELECT')
        for obj in label_objects:
            obj.select_set(True)
        context.view_layer.objects.active = label_objects[0]
        if len(label_objects) > 1:
            bpy.ops.object.join()
        
        labels_obj = context.active_object
        labels_obj.name = "Road_Labels"
        
        # Bisect at terrain boundaries
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        
        bpy.ops.mesh.bisect(plane_co=(terrain_min_x, 0, 0), plane_no=(1, 0, 0),
                           clear_inner=True, clear_outer=False)
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.bisect(plane_co=(terrain_max_x, 0, 0), plane_no=(-1, 0, 0),
                           clear_inner=True, clear_outer=False)
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.bisect(plane_co=(0, terrain_min_y, 0), plane_no=(0, 1, 0),
                           clear_inner=True, clear_outer=False)
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.bisect(plane_co=(0, terrain_max_y, 0), plane_no=(0, -1, 0),
                           clear_inner=True, clear_outer=False)
        
        bpy.ops.object.mode_set(mode='OBJECT')
        
        print(f"✓ Road labels added: {len(filtered_roads)} labels, {len(labels_obj.data.vertices):,} vertices")
        
        return labels_obj
    
    def add_text_before_scale(self, context, dem_obj, text_string, props):
        """Add DEBOSSED text and north arrow"""
        dem_obj_name = dem_obj.name
        
        min_z = min((dem_obj.matrix_world @ v.co).z for v in dem_obj.data.vertices)
        bbox = [dem_obj.matrix_world @ Vector(corner) for corner in dem_obj.bound_box]
        center_x = sum(v.x for v in bbox) / 8
        center_y = sum(v.y for v in bbox) / 8
        
        model_width_m = dem_obj.dimensions.x
        text_size_m = model_width_m * 0.12
        
        future_scale = props.output_width / (model_width_m * 1000)
        depth_m = props.text_depth / 1000 / future_scale
        
        # Extension both above and below for complete penetration
        extension = depth_m * 2
        total_depth = depth_m + extension * 2  # extend both directions
        
        print(f"  Text size: {text_size_m:.1f}m, depth: {depth_m:.3f}m")
        
        bpy.ops.object.text_add(location=(center_x, center_y, min_z))
        text_obj = context.active_object
        text_obj.data.body = text_string
        text_obj.data.size = text_size_m
        text_obj.data.align_x = 'CENTER'
        text_obj.data.align_y = 'CENTER'
        text_obj.data.extrude = total_depth
        text_obj.rotation_euler = (3.14159, 0, 0)
        
        bpy.ops.object.convert(target='MESH')
        text_mesh = context.active_object
        text_mesh.name = "Text_Cutter"
        
        bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')
        # Position so it extends both above and below min_z
        text_mesh.location = (center_x, center_y, min_z + depth_m/2)
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        
        if props.add_north_arrow:
            self.create_north_arrow(context, bbox, min_z, text_size_m, depth_m, extension)
        
        # Join all deboss elements
        bpy.ops.object.select_all(action='DESELECT')
        deboss_objects = [o for o in list(context.scene.objects) 
                         if "Deboss_" in o.name or o.name == "Text_Cutter"]
        
        for deboss_obj in deboss_objects:
            deboss_obj.select_set(True)
        
        if len(deboss_objects) > 1:
            context.view_layer.objects.active = text_mesh
            bpy.ops.object.join()
        elif len(deboss_objects) == 1:
            context.view_layer.objects.active = deboss_objects[0]
        
        deboss_cutter = context.active_object
        deboss_cutter.name = "Final_Deboss_Cutter"
        
        dem_obj = bpy.data.objects.get(dem_obj_name)
        
        bpy.context.view_layer.objects.active = dem_obj
        bpy.ops.object.select_all(action='DESELECT')
        dem_obj.select_set(True)
        
        bool_mod = dem_obj.modifiers.new(name="Boolean_Deboss", type='BOOLEAN')
        bool_mod.operation = 'DIFFERENCE'
        bool_mod.object = deboss_cutter
        bool_mod.solver = 'FAST'
        
        try:
            bpy.ops.object.modifier_apply(modifier=bool_mod.name)
        except Exception as e:
            print(f"  Boolean failed: {e}")
        
        bpy.data.objects.remove(deboss_cutter, do_unlink=True)
        print(f"✓ Text debossed: '{text_string}'")
    
    def create_north_arrow(self, context, bbox, min_z, text_size_m, depth_m, extension):
        """Create north arrow with N and triangle
        
        FIXED: Now extends both above AND below min_z for complete penetration
        Uses direct mesh creation instead of extrude to avoid crashes.
        """
        max_x = max(v.x for v in bbox)
        max_y = max(v.y for v in bbox)
        min_x = min(v.x for v in bbox)
        min_y = min(v.y for v in bbox)
        
        arrow_x = min_x + (max_x - min_x) * 0.85
        arrow_y = min_y + (max_y - min_y) * 0.85
        
        total_depth = depth_m + extension * 2
        
        # Create "N" letter
        bpy.ops.object.text_add(location=(arrow_x, arrow_y, min_z))
        north_n = context.active_object
        north_n.data.body = "N"
        north_n.data.size = text_size_m * 0.6
        north_n.data.align_x = 'CENTER'
        north_n.data.align_y = 'CENTER'
        north_n.data.extrude = total_depth
        north_n.rotation_euler = (3.14159, 0, 0)
        
        bpy.ops.object.convert(target='MESH')
        bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')
        # Position to extend both above and below
        north_n.location = (arrow_x, arrow_y, min_z + depth_m/2)
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        north_n.name = "Deboss_N"
        
        # Create arrow triangle as a proper triangular prism (no extrude)
        arrow_offset = text_size_m * 0.5
        arrow_size = text_size_m * 0.3
        
        # Z coordinates for the prism
        z_bottom = min_z - extension
        z_top = min_z + depth_m + extension
        
        # Triangle vertices - apex points north (+Y)
        apex = (arrow_x, arrow_y + arrow_offset + arrow_size)
        base_left = (arrow_x - arrow_size * 0.4, arrow_y + arrow_offset)
        base_right = (arrow_x + arrow_size * 0.4, arrow_y + arrow_offset)
        
        # Create prism vertices (bottom triangle + top triangle)
        verts = [
            # Bottom face (z_bottom)
            (apex[0], apex[1], z_bottom),
            (base_left[0], base_left[1], z_bottom),
            (base_right[0], base_right[1], z_bottom),
            # Top face (z_top)
            (apex[0], apex[1], z_top),
            (base_left[0], base_left[1], z_top),
            (base_right[0], base_right[1], z_top),
        ]
        
        # Faces: bottom, top, and 3 sides
        faces = [
            (0, 2, 1),     # Bottom (reversed winding for outward normal)
            (3, 4, 5),     # Top
            (0, 1, 4, 3),  # Side 1 (apex to base_left)
            (1, 2, 5, 4),  # Side 2 (base_left to base_right)
            (2, 0, 3, 5),  # Side 3 (base_right to apex)
        ]
        
        mesh = bpy.data.meshes.new("Arrow_Mesh")
        mesh.from_pydata(verts, [], faces)
        mesh.update()
        
        arrow_obj = bpy.data.objects.new("Deboss_Arrow", mesh)
        context.collection.objects.link(arrow_obj)
        
        print(f"  Added north arrow at ({arrow_x:.1f}, {arrow_y:.1f})")
    
    def add_alignment_cutouts(self, context, dem_obj, props):
        """Add triangular prism (bowtie) alignment cutouts on the 4 edges
        
        Creates triangular prisms pointing OUTWARD from each edge. When two tiles meet,
        the triangular cutouts form a bowtie shape for alignment pins.
        
        Edge Inset:
        - 100% = apex exactly at edge (full triangle visible on this tile)
        - 0% = apex outside tile (triangle not visible on this tile, only on adjacent)
        
        Uses EXACT boolean solver and processes each cutout individually for reliability.
        """
        dem_obj_name = dem_obj.name
        print(f"  Adding bowtie alignment cutouts")
        
        bbox = [dem_obj.matrix_world @ Vector(corner) for corner in dem_obj.bound_box]
        min_x = min(v.x for v in bbox)
        max_x = max(v.x for v in bbox)
        min_y = min(v.y for v in bbox)
        max_y = max(v.y for v in bbox)
        min_z = min((dem_obj.matrix_world @ v.co).z for v in dem_obj.data.vertices)
        
        model_width_m = dem_obj.dimensions.x
        future_scale = props.output_width / (model_width_m * 1000)
        
        # Convert mm settings to meters
        size_m = (props.cutout_size / 1000) / future_scale
        depth_m = (props.cutout_depth / 1000) / future_scale
        half_size = size_m / 2
        
        inset_pct = props.cutout_inset / 100.0  # Position along edge
        
        # Extension below surface - make it generous for clean boolean operations
        extension_m = depth_m * 2
        
        width = max_x - min_x
        height = max_y - min_y
        
        print(f"  Triangle size: {size_m:.3f}m ({props.cutout_size:.1f}mm final)")
        print(f"  Cutout depth: {depth_m:.3f}m ({props.cutout_depth:.1f}mm final)")
        
        edge_inset_pct = props.cutout_edge_inset / 100.0
        edge_offset = half_size * (2 * edge_inset_pct - 1)
        
        print(f"  Edge inset: {props.cutout_edge_inset:.0f}% (offset: {edge_offset:.3f}m)")
        
        # Z coordinates - extend further for reliable boolean
        z_bottom = min_z - extension_m
        z_top = min_z + depth_m + (extension_m * 0.1)  # Slight extension above too
        
        # Cutout configurations: (center_x, center_y, rotation_angle, name)
        cutout_configs = [
            # South edge - triangles point -Y (outward/south)
            (min_x + width * inset_pct, min_y + edge_offset, math.pi, "South_W"),
            (max_x - width * inset_pct, min_y + edge_offset, math.pi, "South_E"),
            # North edge - triangles point +Y (outward/north)  
            (min_x + width * inset_pct, max_y - edge_offset, 0, "North_W"),
            (max_x - width * inset_pct, max_y - edge_offset, 0, "North_E"),
            # West edge - triangles point -X (outward/west)
            (min_x + edge_offset, min_y + height * inset_pct, math.pi/2, "West_S"),
            (min_x + edge_offset, max_y - height * inset_pct, math.pi/2, "West_N"),
            # East edge - triangles point +X (outward/east)
            (max_x - edge_offset, min_y + height * inset_pct, -math.pi/2, "East_S"),
            (max_x - edge_offset, max_y - height * inset_pct, -math.pi/2, "East_N"),
        ]
        
        successful_cuts = 0
        failed_cuts = 0
        
        # Process each cutout individually for reliability
        for cx, cy, rot_z, name in cutout_configs:
            cos_r = math.cos(rot_z)
            sin_r = math.sin(rot_z)
            
            # Local triangle: apex at (0, +half_size), base at y=-half_size
            local_pts = [
                (0, half_size),           # Apex
                (-half_size, -half_size), # Base left  
                (half_size, -half_size),  # Base right
            ]
            
            # Transform to world coordinates
            prism_verts = []
            for lx, ly in local_pts:
                wx = lx * cos_r - ly * sin_r + cx
                wy = lx * sin_r + ly * cos_r + cy
                prism_verts.append((wx, wy, z_bottom))
            for lx, ly in local_pts:
                wx = lx * cos_r - ly * sin_r + cx
                wy = lx * sin_r + ly * cos_r + cy
                prism_verts.append((wx, wy, z_top))
            
            prism_faces = [
                (0, 2, 1),        # Bottom
                (3, 4, 5),        # Top
                (0, 1, 4, 3),     # Side 1
                (1, 2, 5, 4),     # Side 2
                (2, 0, 3, 5),     # Side 3
            ]
            
            # Create individual mesh for this cutout
            mesh = bpy.data.meshes.new(f"Cutout_{name}_Mesh")
            mesh.from_pydata(prism_verts, [], prism_faces)
            mesh.update()
            
            cutout_obj = bpy.data.objects.new(f"Cutout_{name}", mesh)
            context.collection.objects.link(cutout_obj)
            
            # Get fresh reference to DEM object
            dem_obj = bpy.data.objects.get(dem_obj_name)
            if dem_obj is None or len(dem_obj.data.vertices) == 0:
                print(f"    ERROR: DEM object missing for {name}!")
                bpy.data.objects.remove(cutout_obj, do_unlink=True)
                failed_cuts += 1
                continue
            
            # Apply boolean with EXACT solver
            bpy.context.view_layer.objects.active = dem_obj
            bpy.ops.object.select_all(action='DESELECT')
            dem_obj.select_set(True)
            
            bool_mod = dem_obj.modifiers.new(name=f"Boolean_{name}", type='BOOLEAN')
            bool_mod.operation = 'DIFFERENCE'
            bool_mod.object = cutout_obj
            bool_mod.solver = 'EXACT'  # More reliable than FAST
            
            try:
                bpy.ops.object.modifier_apply(modifier=bool_mod.name)
                successful_cuts += 1
                print(f"    ✓ {name}: ({cx:.1f}, {cy:.1f})")
            except Exception as e:
                print(f"    ✗ {name} boolean failed: {e}")
                # Try with FAST solver as fallback
                try:
                    bool_mod2 = dem_obj.modifiers.new(name=f"Boolean_{name}_retry", type='BOOLEAN')
                    bool_mod2.operation = 'DIFFERENCE'
                    bool_mod2.object = cutout_obj
                    bool_mod2.solver = 'FAST'
                    bpy.ops.object.modifier_apply(modifier=bool_mod2.name)
                    successful_cuts += 1
                    print(f"    ✓ {name}: ({cx:.1f}, {cy:.1f}) [FAST fallback]")
                except Exception as e2:
                    print(f"    ✗ {name} fallback also failed: {e2}")
                    failed_cuts += 1
            
            # Clean up cutout object
            bpy.data.objects.remove(cutout_obj, do_unlink=True)
        
        print(f"✓ Bowtie alignment cutouts: {successful_cuts}/8 successful")
        if failed_cuts > 0:
            print(f"  WARNING: {failed_cuts} cutouts failed")
    
    def add_mounting_holes(self, context, dem_obj, props):
        """Add cylindrical mounting holes near the 4 corners
        
        Creates cylinders that are subtracted from the bottom of the model,
        allowing the tile to be mounted from the back with screws or pins.
        """
        dem_obj_name = dem_obj.name
        print(f"  Adding mounting holes")
        
        bbox = [dem_obj.matrix_world @ Vector(corner) for corner in dem_obj.bound_box]
        min_x = min(v.x for v in bbox)
        max_x = max(v.x for v in bbox)
        min_y = min(v.y for v in bbox)
        max_y = max(v.y for v in bbox)
        min_z = min((dem_obj.matrix_world @ v.co).z for v in dem_obj.data.vertices)
        
        model_width_m = dem_obj.dimensions.x
        future_scale = props.output_width / (model_width_m * 1000)
        
        # Convert mm settings to meters (pre-scale)
        diameter_m = (props.mounting_hole_diameter / 1000) / future_scale
        radius_m = diameter_m / 2
        
        # Use same depth as alignment cutouts
        depth_m = (props.cutout_depth / 1000) / future_scale
        
        # Extension below surface to ensure clean cut
        extension_m = 1.0
        
        width = max_x - min_x
        height = max_y - min_y
        
        # Inset from corners
        inset_pct = props.mounting_hole_inset / 100.0
        inset_x = width * inset_pct
        inset_y = height * inset_pct
        
        print(f"  Hole diameter: {diameter_m:.3f}m ({props.mounting_hole_diameter:.1f}mm final)")
        print(f"  Hole depth: {depth_m:.3f}m ({props.cutout_depth:.1f}mm final)")
        print(f"  Corner inset: {inset_pct*100:.0f}%")
        
        # Z coordinates for cylinders
        z_bottom = min_z - extension_m
        z_top = min_z + depth_m
        
        # 4 corner positions
        hole_positions = [
            (min_x + inset_x, min_y + inset_y, "SW"),  # Southwest corner
            (max_x - inset_x, min_y + inset_y, "SE"),  # Southeast corner
            (min_x + inset_x, max_y - inset_y, "NW"),  # Northwest corner
            (max_x - inset_x, max_y - inset_y, "NE"),  # Northeast corner
        ]
        
        # Create cylinder geometry
        # Use 16 segments for a smooth circle
        segments = 16
        
        all_verts = []
        all_faces = []
        vert_offset = 0
        
        for cx, cy, name in hole_positions:
            # Create circle vertices at bottom and top
            bottom_verts = []
            top_verts = []
            
            for i in range(segments):
                angle = 2 * math.pi * i / segments
                vx = cx + radius_m * math.cos(angle)
                vy = cy + radius_m * math.sin(angle)
                bottom_verts.append((vx, vy, z_bottom))
                top_verts.append((vx, vy, z_top))
            
            # Add center vertices for top and bottom caps
            bottom_center = (cx, cy, z_bottom)
            top_center = (cx, cy, z_top)
            
            # Add vertices to the list
            # Order: bottom circle, top circle, bottom center, top center
            all_verts.extend(bottom_verts)
            all_verts.extend(top_verts)
            all_verts.append(bottom_center)
            all_verts.append(top_center)
            
            v = vert_offset
            
            # Create faces
            # Side faces (quads connecting bottom and top circles)
            for i in range(segments):
                i_next = (i + 1) % segments
                face = (
                    v + i,                    # bottom current
                    v + i_next,               # bottom next
                    v + segments + i_next,    # top next
                    v + segments + i,         # top current
                )
                all_faces.append(face)
            
            # Bottom cap (triangles from center to edge)
            bottom_center_idx = v + 2 * segments
            for i in range(segments):
                i_next = (i + 1) % segments
                face = (bottom_center_idx, v + i_next, v + i)  # Reversed winding for outward normal
                all_faces.append(face)
            
            # Top cap (triangles from center to edge)
            top_center_idx = v + 2 * segments + 1
            for i in range(segments):
                i_next = (i + 1) % segments
                face = (top_center_idx, v + segments + i, v + segments + i_next)
                all_faces.append(face)
            
            vert_offset += 2 * segments + 2  # circle verts + 2 center verts
            
            print(f"    {name} corner: ({cx:.1f}, {cy:.1f})")
        
        # Create mesh
        mesh = bpy.data.meshes.new("Mounting_Holes_Mesh")
        mesh.from_pydata(all_verts, [], all_faces)
        mesh.update()
        
        holes_obj = bpy.data.objects.new("Mounting_Holes_Combined", mesh)
        context.collection.objects.link(holes_obj)
        
        # Apply boolean
        dem_obj = bpy.data.objects.get(dem_obj_name)
        if dem_obj is None or len(dem_obj.data.vertices) == 0:
            print(f"  ERROR: DEM object missing!")
            bpy.data.objects.remove(holes_obj, do_unlink=True)
            return
        
        bpy.context.view_layer.objects.active = dem_obj
        bpy.ops.object.select_all(action='DESELECT')
        dem_obj.select_set(True)
        
        bool_mod = dem_obj.modifiers.new(name="Boolean_MountingHoles", type='BOOLEAN')
        bool_mod.operation = 'DIFFERENCE'
        bool_mod.object = holes_obj
        bool_mod.solver = 'EXACT'  # More reliable than FAST
        
        try:
            bpy.ops.object.modifier_apply(modifier=bool_mod.name)
        except Exception as e:
            print(f"  Boolean failed with EXACT, trying FAST: {e}")
            # Fallback to FAST
            try:
                bool_mod2 = dem_obj.modifiers.new(name="Boolean_MountingHoles_retry", type='BOOLEAN')
                bool_mod2.operation = 'DIFFERENCE'
                bool_mod2.object = holes_obj
                bool_mod2.solver = 'FAST'
                bpy.ops.object.modifier_apply(modifier=bool_mod2.name)
            except Exception as e2:
                print(f"  Boolean also failed with FAST: {e2}")
        
        bpy.data.objects.remove(holes_obj, do_unlink=True)
        print(f"✓ Mounting holes added (4 corners)")
    
    def calculate_scale(self, obj, props):
        # Scale so final dimensions are in mm (1 Blender unit = 1mm)
        current_width_m = obj.dimensions.x
        target_width_mm = props.output_width
        scale_factor = target_width_mm / (current_width_m * 1000)
        final_scale = scale_factor * 1000
        return (final_scale, final_scale, final_scale)
    
    def scale_object(self, obj, scale):
        obj.scale = scale
        bpy.ops.object.transform_apply(scale=True)
        final = obj.dimensions
        print(f"✓ Scaled to: {final.x:.1f}×{final.y:.1f}×{final.z:.1f}mm")
    
    def export_stl(self, obj, props, suffix=""):
        """Export to STL"""
        filename = os.path.splitext(os.path.basename(props.dem_file))[0]
        
        if props.output_path and os.path.isdir(props.output_path):
            output = os.path.join(props.output_path, f"{filename}{suffix}.stl")
        else:
            output = os.path.join(os.path.dirname(props.dem_file), f"{filename}{suffix}.stl")
        
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        
        # Fix non-manifold geometry before export
        self.make_manifold(obj)
        
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        
        print(f"  Writing STL: {os.path.basename(output)}")
        
        bpy.ops.export_mesh.stl(
            filepath=output,
            use_selection=True,
            global_scale=1.0,
            ascii=False
        )
            
        return output
    
    def print_summary(self, obj, output, dem_width, dem_height, vertices, elapsed_time):
        size = os.path.getsize(output) / (1024 * 1024)
        dims = obj.dimensions
        faces = len(obj.data.polygons)
        
        if elapsed_time < 60:
            time_str = f"{elapsed_time:.1f} seconds"
        elif elapsed_time < 3600:
            time_str = f"{int(elapsed_time // 60)} minutes {int(elapsed_time % 60)} seconds"
        else:
            time_str = f"{int(elapsed_time // 3600)} hours {int((elapsed_time % 3600) // 60)} minutes"
        
        print("\n" + "="*70)
        print("PROCESSING COMPLETE")
        print("="*70)
        print(f"Source DEM: {dem_width:.0f}×{dem_height:.0f}m")
        print(f"Print size: {dims.x:.1f}×{dims.y:.1f}×{dims.z:.1f}mm")
        print(f"Mesh: {vertices:,} vertices, {faces:,} faces")
        print(f"Output: {os.path.basename(output)}")
        print(f"File size: {size:.1f} MB")
        print(f"Time: {time_str}")
        print("="*70 + "\n")


class DEMPRINT_OT_BatchProcess(Operator):
    """Batch process multiple DEM files"""
    bl_idname = "demprint.batch_process"
    bl_label = "Batch Process DEMs"
    bl_options = {'REGISTER'}
    
    @classmethod
    def poll(cls, context):
        props = context.scene.dem_print_props
        return props.batch_folder and os.path.isdir(props.batch_folder)
    
    def execute(self, context):
        props = context.scene.dem_print_props
        
        # Find all DEM files
        valid_extensions = ['.tif', '.tiff', '.asc', '.dem', '.hgt', '.img']
        dem_files = []
        
        if props.batch_recursive:
            for root, dirs, files in os.walk(props.batch_folder):
                for f in files:
                    if os.path.splitext(f)[1].lower() in valid_extensions:
                        dem_files.append(os.path.join(root, f))
        else:
            for f in os.listdir(props.batch_folder):
                if os.path.splitext(f)[1].lower() in valid_extensions:
                    dem_files.append(os.path.join(props.batch_folder, f))
        
        if not dem_files:
            self.report({'ERROR'}, "No DEM files found in folder")
            return {'CANCELLED'}
        
        dem_files.sort()
        
        print("\n" + "="*70)
        print("BATCH PROCESSING")
        print("="*70)
        print(f"Found {len(dem_files)} DEM files")
        if props.add_buildings and props.building_shapefile:
            print(f"Using building shapefile: {os.path.basename(props.building_shapefile)}")
        print("="*70 + "\n")
        
        # Store original DEM file setting
        original_dem = props.dem_file
        
        successful = 0
        failed = 0
        batch_start = time.time()
        
        for i, dem_path in enumerate(dem_files):
            print(f"\n{'='*70}")
            print(f"BATCH {i+1}/{len(dem_files)}: {os.path.basename(dem_path)}")
            print(f"{'='*70}")
            
            # Set the DEM file
            props.dem_file = dem_path
            
            # Clear existing objects
            bpy.ops.object.select_all(action='SELECT')
            bpy.ops.object.delete(use_global=False)
            
            # Process this DEM (building_shapefile stays the same for all tiles)
            try:
                result = bpy.ops.demprint.process()
                if result == {'FINISHED'}:
                    successful += 1
                else:
                    failed += 1
                    print(f"  FAILED: {dem_path}")
            except Exception as e:
                failed += 1
                print(f"  ERROR: {e}")
            
            # Clear scene for next file
            bpy.ops.object.select_all(action='SELECT')
            bpy.ops.object.delete(use_global=False)
        
        # Restore original setting
        props.dem_file = original_dem
        
        batch_elapsed = time.time() - batch_start
        
        print("\n" + "="*70)
        print("BATCH COMPLETE")
        print("="*70)
        print(f"Processed: {len(dem_files)} files")
        print(f"Successful: {successful}")
        print(f"Failed: {failed}")
        if batch_elapsed < 60:
            print(f"Total time: {batch_elapsed:.1f} seconds")
        elif batch_elapsed < 3600:
            print(f"Total time: {int(batch_elapsed // 60)}m {int(batch_elapsed % 60)}s")
        else:
            print(f"Total time: {int(batch_elapsed // 3600)}h {int((batch_elapsed % 3600) // 60)}m")
        print("="*70 + "\n")
        
        self.report({'INFO'}, f"Batch complete: {successful} successful, {failed} failed")
        
        return {'FINISHED'}


class DEMPRINT_PT_MainPanel(Panel):
    bl_label = "DEM to 3D Print"
    bl_idname = "DEMPRINT_PT_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'DEM Print'
    
    def draw(self, context):
        layout = self.layout
        props = context.scene.dem_print_props
        
        # Input
        box = layout.box()
        box.label(text="Input:", icon='FILE')
        box.prop(props, "dem_file", text="DEM")
        box.prop(props, "output_path", text="Output")
        
        # Print size
        box = layout.box()
        box.label(text="Print Size:", icon='ARROW_LEFTRIGHT')
        box.prop(props, "output_width")
        
        # Quality
        box = layout.box()
        box.label(text="Quality:", icon='SETTINGS')
        box.prop(props, "subdivision_levels")
        box.prop(props, "use_smooth_relief")
        box.prop(props, "fill_nodata")
        
        # Base
        box = layout.box()
        box.label(text="Base:", icon='MESH_CUBE')
        box.prop(props, "extrude_depth")
        box.prop(props, "auto_cut_elevation")
        if not props.auto_cut_elevation:
            box.prop(props, "cut_elevation")
        
        # Text
        box = layout.box()
        box.label(text="Text:", icon='FONT_DATA')
        box.prop(props, "text_depth")
        box.prop(props, "add_north_arrow")
        
        # Alignment cutouts
        box = layout.box()
        box.label(text="Tile Alignment:", icon='MOD_LATTICE')
        box.prop(props, "add_alignment_cutouts")
        if props.add_alignment_cutouts:
            box.prop(props, "cutout_size")
            box.prop(props, "cutout_depth")
            box.prop(props, "cutout_inset")
            box.prop(props, "cutout_edge_inset")
            box.label(text="Triangular bowtie connectors", icon='INFO')
        
        # Mounting holes
        box.separator()
        box.prop(props, "add_mounting_holes")
        if props.add_mounting_holes:
            box.prop(props, "mounting_hole_diameter")
            box.prop(props, "mounting_hole_inset")
            row = box.row()
            row.label(text=f"Uses cutout depth: {props.cutout_depth:.1f}mm", icon='INFO')
        
        # Buildings
        box = layout.box()
        box.label(text="Buildings:", icon='HOME')
        box.prop(props, "add_buildings")
        if props.add_buildings:
            box.prop(props, "building_source", text="Source")
            
            if props.building_source == 'SHAPEFILE':
                box.prop(props, "building_shapefile", text="Shapefile")
                box.prop(props, "building_height")
                box.prop(props, "building_depth")
                box.label(text="2D footprints extruded to height", icon='INFO')
            
            elif props.building_source == 'CITYJSON':
                box.prop(props, "building_cityjson", text="CityJSON")
                box.prop(props, "cityjson_use_lod", text="LoD")
                box.prop(props, "building_depth", text="Extend Below")
                box.label(text="3D LoD2 buildings with roof shapes", icon='INFO')
            
            box.label(text="Exported as separate STL", icon='EXPORT')
        
        # Roads
        box = layout.box()
        box.label(text="Roads:", icon='TRACKING')
        box.prop(props, "add_roads")
        if props.add_roads:
            box.prop(props, "road_shapefile", text="Shapefile")
            box.prop(props, "road_width")
            box.prop(props, "road_height")
            box.prop(props, "road_depth")
            box.label(text="Exported as separate STL", icon='INFO')
            box.separator()
            box.prop(props, "add_road_labels")
            if props.add_road_labels:
                box.prop(props, "road_label_size")
                box.prop(props, "road_label_height")
                box.prop(props, "road_label_min_length")
                box.label(text="Labels exported as separate STL", icon='INFO')
        
        # Trails
        box = layout.box()
        box.label(text="Trails:", icon='CURVE_PATH')
        box.prop(props, "add_trails")
        if props.add_trails:
            box.prop(props, "trail_shapefile", text="Shapefile")
            box.prop(props, "trail_width")
            box.prop(props, "trail_height")
            box.prop(props, "trail_depth")
            box.label(text="Exported as separate STL", icon='INFO')
        
        # Process button
        layout.separator()
        row = layout.row()
        row.scale_y = 2.0
        
        file_ok = props.dem_file != "" and os.path.exists(props.dem_file)
        
        if file_ok:
            valid_extensions = ['.tif', '.tiff', '.asc', '.dem', '.hgt', '.img']
            file_ext = os.path.splitext(props.dem_file)[1].lower()
            
            if file_ext in valid_extensions:
                row.operator("demprint.process", icon='PLAY', text="Process DEM")
            else:
                row.enabled = False
                row.label(text=f"Invalid: {file_ext}", icon='ERROR')
        else:
            row.enabled = False
            row.label(text="Select DEM file", icon='INFO')
        
        # Batch Processing Section
        layout.separator()
        box = layout.box()
        box.label(text="Batch Processing:", icon='FILE_FOLDER')
        box.prop(props, "batch_folder", text="DEM Folder")
        box.prop(props, "batch_recursive")
        
        if props.add_buildings and props.building_shapefile:
            box.label(text=f"Buildings: {os.path.basename(props.building_shapefile)}", icon='HOME')
        
        # Count files in folder
        if props.batch_folder and os.path.isdir(props.batch_folder):
            valid_extensions = ['.tif', '.tiff', '.asc', '.dem', '.hgt', '.img']
            count = 0
            if props.batch_recursive:
                for root, dirs, files in os.walk(props.batch_folder):
                    count += sum(1 for f in files if os.path.splitext(f)[1].lower() in valid_extensions)
            else:
                count = sum(1 for f in os.listdir(props.batch_folder) 
                           if os.path.splitext(f)[1].lower() in valid_extensions)
            box.label(text=f"Found {count} DEM files", icon='INFO')
            
            row = box.row()
            row.scale_y = 1.5
            row.operator("demprint.batch_process", icon='PLAY', text=f"Process All ({count})")
        else:
            box.label(text="Select folder to batch process", icon='INFO')


classes = (
    DEMPrintProperties,
    DEMPRINT_OT_Process,
    DEMPRINT_OT_BatchProcess,
    DEMPRINT_PT_MainPanel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.dem_print_props = PointerProperty(type=DEMPrintProperties)
    print("\n" + "="*70)
    print("DEM to 3D Print STL v6.5")
    print("="*70)
    print("Features: Reliable booleans, Mounting holes, CityJSON, Shapefiles, Batch")
    print("Location: Sidebar (N) → DEM Print tab")
    print("="*70 + "\n")

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.dem_print_props

if __name__ == "__main__":
    register()
