#!/usr/bin/env python3
"""NavCore: add a deterministic serial runner for ROS 2 bags (ros2_serial_msckf) to ov_msckf.
Run from ~/navcore_ws/src/open_vins on branch navcore_t4:  python3 scripts/navcore_serial_patch.py
Writes ov_msckf/src/ros2_serial_msckf.cpp (copied from scripts/ros2_serial_msckf.cpp), adds rosbag2_cpp to
ov_msckf/cmake/ROS2.cmake and ov_msckf/package.xml, and declares the new executable next to run_subscribe_msckf.
No existing source file changes, so every other program builds exactly as before.
Every edit is anchored on text that must occur exactly once; on any mismatch nothing is written."""
import os, shutil, subprocess, sys

CM, PX, DST = 'ov_msckf/cmake/ROS2.cmake', 'ov_msckf/package.xml', 'ov_msckf/src/ros2_serial_msckf.cpp'
SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ros2_serial_msckf.cpp')
for p in (CM, PX, SRC):
    if not os.path.isfile(p):
        sys.exit(f'not found: {p}  (run from ~/navcore_ws/src/open_vins, with ros2_serial_msckf.cpp in scripts/)')
cm, px = open(CM).read(), open(PX).read()
if 'ros2_serial_msckf' in cm or os.path.exists(DST):
    sys.exit('already patched (ros2_serial_msckf found); nothing changed')
br = subprocess.run(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], capture_output=True, text=True).stdout.strip()
if br != 'navcore_t4':
    sys.exit(f'on branch {br!r}, expected navcore_t4; nothing changed')
if subprocess.run(['git', 'status', '--porcelain', CM, PX], capture_output=True, text=True).stdout.strip():
    sys.exit('uncommitted changes in ROS2.cmake or package.xml; commit them first. Nothing changed.')


def rep(s, old, new, what):
    if s.count(old) != 1:
        sys.exit(f'anchor for {what} found {s.count(old)} times (need 1); nothing changed')
    return s.replace(old, new)


cm = rep(cm, 'find_package(ov_init REQUIRED)\n', 'find_package(ov_init REQUIRED)\nfind_package(rosbag2_cpp REQUIRED) # NavCore: serial runner\n', 'find_package')
cm = rep(cm, 'install(TARGETS run_subscribe_msckf DESTINATION lib/${PROJECT_NAME})\n',
         'install(TARGETS run_subscribe_msckf DESTINATION lib/${PROJECT_NAME})\n\n'
         '# NavCore: deterministic serial runner for ROS 2 bags (reads the bag directly, frames in recorded order)\n'
         'add_executable(ros2_serial_msckf src/ros2_serial_msckf.cpp)\n'
         'ament_target_dependencies(ros2_serial_msckf ${ament_libraries} rosbag2_cpp)\n'
         'target_link_libraries(ros2_serial_msckf ov_msckf_lib ${thirdparty_libraries})\n'
         'install(TARGETS ros2_serial_msckf DESTINATION lib/${PROJECT_NAME})\n', 'executable')
px = rep(px, '    <depend condition="$ROS_VERSION == 2">ov_init</depend>\n',
         '    <depend condition="$ROS_VERSION == 2">ov_init</depend>\n    <depend condition="$ROS_VERSION == 2">rosbag2_cpp</depend>\n', 'package.xml')
shutil.copyfile(SRC, DST)
open(CM, 'w').write(cm)
open(PX, 'w').write(px)
print(subprocess.run(['git', 'status', '--short', CM, PX, DST], capture_output=True, text=True).stdout.strip())
print('patched. Next: build ov_msckf (it now also builds ros2_serial_msckf)')
