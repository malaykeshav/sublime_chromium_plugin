import sublime
import sublime_plugin

import select
import subprocess
import time
import threading
import os

class Platform:
  ANDROID = 0
  CHROME_OS = 1
  CHROME_OS_DEVICE = 2
  LINUX = 3

class Operation:
  GENERATE_GN_ARGS = 0
  BUILD = 1
  RUN = 2
  DEPLOY = 3
  BUILD_AND_RUN = 4
  BUILD_AND_DEPLOY = 5
  SHOW_OUTPUT_PANEL = 6
  REPEAT_PREVIOUS_OPERATION = 7

class BuildTargets:
  # Release targets
  CHROME = 0
  CHROME_SANDBOX = 1
  CHROME_PUBLIC_APK = 2
  WEBUI_CLOSURE_COMPILE = 3

  # Test targets
  APP_LIST_UNITTEST = 4
  ASH_UNITTESTS = 5
  AURA_UNITTESTS = 6
  BROWSERTESTS = 7
  COMPOSITOR_UNITTESTS = 8
  CONTENT_BROWSERTESTS = 9
  CONTENT_UNITTESTS = 10
  CC_UNITTESTS = 11
  DISPLAY_UNITTESTS = 12
  GFX_UNITTESTS = 13
  INTERACTIVE_UI_TESTS = 14
  UNITTESTS = 15
  VIEWS_UNITTESTS = 16
  VIZ_UNITTESTS = 17
  WEBKIT_UNITTESTS = 18
  WM_UNITTESTS = 19

TARGETS = [
  'chrome',
  'chrome_sandbox',
  'chrome_public_apk',
  'webui_closure_compile',
  'app_list_unittests',
  'ash_unittests',
  'aura_unittests',
  'browser_tests',
  'compositor_unittests',
  'content_browsertests',
  'content_unittests',
  'cc_unittests',
  'display_unittests',
  'gfx_unittests',
  'interactive_ui_tests',
  'unit_tests',
  'views_unittests',
  'viz_unittests',
  'webkit_unit_tests',
  'wm_unittests',
]

# Default targets for each platform
DEFAULT_OS_TARGETS = [
  [BuildTargets.CHROME_PUBLIC_APK],  # android
  [BuildTargets.CHROME],             # chrome os
  [BuildTargets.CHROME, BuildTargets.CHROME_SANDBOX], # chrome os device
  [BuildTargets.CHROME],             # linux
]

GN_ARGS_FILE_NAME = "args.gn"
COMMAND_LINE_FLAGS_FILE_NAME = "command_line_flags.txt"
CHROME_OUTPUT_FILE_NAME = "chrome_output.txt"

# Bash command line interface for this plugin.
BASH_INTERFACE = None

LINE_REGEX = r'(?:^|[)] )[.\\\\/]*([a-z]?:?[\\w.\\\\/]+)[(:]([0-9]+)[,:]?([0-9]+)?[)]?:?(.*)$'

# Token identifier to identify the end of a output/input stream.
STREAM_END_TOKEN = 'SUBLIME_STREAM_END'

# Settings key:
GN_ARGS_FILE_KEY = 'GN_ARGS_FILE_KEY'
GN_ARGS_OUT_DIR_KEY = 'GN_ARGS_OUT_DIR_KEY'
GN_ARGS_SOURCE_FILE_KEY = 'GN_ARGS_SOURCE_FILE_KEY'

# Popen object for the current build process.
BUILD_PROCESS = None

# Popen object for the current executing chrome binary
CHROME_PROCESS = None

class BashInterface:
  output_panel = None
  stdin_lock = threading.Lock()
  def Get():
    global BASH_INTERFACE
    if BASH_INTERFACE is None:
      BASH_INTERFACE = BashInterface()
    return BASH_INTERFACE

  def __init__(self):
    self.BASH = subprocess.Popen(['/bin/bash'], shell=True,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    self.__RunCmd("source ~/.bashrc\n")
    print (self.__GetResult())

  def __RunCmd(self, cmd):
    with self.stdin_lock:
      self.BASH.stdin.write(bytes(cmd, 'UTF-8'))
      self.BASH.stdin.flush()

  def __GetResult(self, timeout=0.5):
    result = ""

    r, w, e = select.select([self.BASH.stdout], [], [], timeout)
    while self.BASH.stdout in r:
      result += os.read(self.BASH.stdout.fileno(), 10).decode("utf-8")
      r, w, e = select.select([self.BASH.stdout], [], [], 0.5)

    return result

  def __StreamResult(self, file=None, timeout=0.5, end_token=None):
    if file:
      threading.Thread(
          target=self.__StreamFileContent, name="StreamFileContent",
          args=(file, self.output_panel, end_token)).start()
    else:
      threading.Thread(
          target=self.__StreamResultTarget, name="StreamStdOutContent",
          args=(self.BASH.stdout, timeout, self.output_panel)).start()


  def __StreamResultTarget(self, stdout, timeout, output_panel):
    source = stdout.fileno()

    result = ""
    data = ""

    r, w, e = select.select([source], [], [], timeout)
    while source in r:
      data = os.read(source, 2**8).decode("utf-8")
      result += data
      r, w, e = select.select([source], [], [], timeout)
    
    if len(result) == 0:
      result = "No output generated"

    if output_panel:
      output_panel.Print(result)
    else:
      print (result)


  def __StreamFileContent(self, filename, output_panel, end_token):
    with open(filename, 'r') as file:
      current_line = ""
      while end_token not in current_line:
        current_line = file.readline()
        if len(current_line) > 0 and end_token not in current_line:
          output_panel.Print(current_line.rstrip())
      output_panel.Print('End out Output Stream')


  def __RunCmdAndGetResult(self, cmd):
    self.__RunCmd(cmd)
    return self.__GetResult()

  def IsChromeSdk(self):
    output = self.__RunCmdAndGetResult("printenv SDK_BOARD\n")
    return False if len(output) == 0 else true

  def GetChromeSdkBoard(self):
    output = self.__RunCmdAndGetResult("printenv SDK_BOARD\n")
    return "" if len(output) == 0 else output

  def MaybeCreateFile(self, path, name):
    self.__RunCmd("touch " + path + name + "\n")

  def CreateFile(self, file_path):
    with open(file_path, "w+") as file:
      file.write("")

  def CreateDirectory(self, path):
    self.__RunCmd("mkdir -p " + path)

  def CopyFileContents(self, source, target):
    self.__RunCmd("cat " + source + " > " + target + "\n")

  def GenerateGnArgs(self, path):
    print ("Will run: " + "gn gen \'" + path + "\'\n")
    self.__RunCmd("gn gen \'" + path + "\'\n")
    self.output_panel.Print("gn gen \'" + path + "\'")
    self.__StreamResult(timeout=10)

  def GoToDirectory(self, path):
    self.__RunCmd("cd " + path + "\n")
    self.__StreamResult(timeout=1)

  def SetOutputPanel(self, output_panel):
    self.output_panel = output_panel

  def GetCommandLineFlags(self, path):
    flags = []
    print ("Opening flags file: " + path)
    with open(path, 'r') as file:
      for current_line in file:
        if current_line[0] == '#' or len(current_line.rstrip()) == 0:
          continue
        flags.append(current_line.rstrip())
        current_line = file.readline()
    return flags

  def TerminateProcess(process):
    if not process:
      return

    if process.poll():
      process.terminate()    

  def Build(self, build_settings):
    build_output_filename = "/build_output.txt"
    build_output_file_path = build_settings.build_dir + build_output_filename

    global BUILD_PROCESS

    # Stop any previous build process if they are still running.
    BashInterface.TerminateProcess(BUILD_PROCESS)

    # Inform the thread to stop reading the output
    # self.__RunCmd("echo \'\nSTREAM_END_TOKEN\' >> " + build_output_file_path)


    # Reset the output file and start reading from it.
    self.CreateFile(build_output_file_path)
    self.__StreamResult(file=build_output_file_path, end_token=STREAM_END_TOKEN)

    target_str = " ".join(build_settings.targets)

    cmd =  ['cd', build_settings.project_src_path, ';']
    cmd += ['ninja', '-j1024', '-C', build_settings.build_dir, target_str]
    cmd += ['>', build_output_file_path]
    cmd += [';', 'echo', STREAM_END_TOKEN, '>>', build_output_file_path]
    build_cmd = " ".join(cmd)


    # Execute the command to build on a separate process that logs output into a file.
    BUILD_PROCESS = subprocess.Popen(build_cmd, shell=True)

    self.output_panel.Print("Build Process ID: " + str(BUILD_PROCESS.pid))

  def Run(self, build_settings):
    target_binary = build_settings.build_dir + "./chrome"
    chrome_output_file_path = build_settings.build_dir + CHROME_OUTPUT_FILE_NAME
    command_line_flags_path = (build_settings.project_path + "/" + 
                              COMMAND_LINE_FLAGS_FILE_NAME)
    
    flags = self.GetCommandLineFlags(command_line_flags_path)

    # Reset the output file and start reading from it.
    self.CreateFile(chrome_output_file_path)
    self.__StreamResult(file=chrome_output_file_path, end_token=STREAM_END_TOKEN)

    global CHROME_PROCESS
    # Terminate any previously running chrome binary execution
    BashInterface.TerminateProcess(CHROME_PROCESS)
    
    cmd = []
    cmd += ['cd', build_settings.build_dir, ';']
    cmd += [target_binary]
    cmd += flags
    cmd += ['&>', chrome_output_file_path]
    cmd += [';', 'echo', STREAM_END_TOKEN, '>>', chrome_output_file_path]

    self.output_panel.Print(" ".join(cmd))
    CHROME_PROCESS =  subprocess.Popen(" ".join(cmd), shell=True)
    self.output_panel.Print("Chrome Process ID: " + str(CHROME_PROCESS.pid))


class BuildSettings:
  project_src_path = None
  project_path = None
  platform_str = None
  build_dir = None
  targets = []

  def __init__(self, window, args):
    self.project_src_path = window.extract_variables()['folder']
    self.project_path = window.extract_variables()['project_path']

    if "device" not in args:
      args["device"] = ""

    platform = args['platform']

    self.platform_str = ['android', 'cros', args["device"], 'linux'][platform]
    self.build_dir = (self.project_src_path + '/out_' +
                     self.platform_str + '/Default/')

    self.targets = []
    for target in DEFAULT_OS_TARGETS[platform]:
      self.targets.append(TARGETS[target])

  def __eq__(self, obj):
    return (isinstance(obj, BuildSettings) and
            self.project_src_path == obj.project_src_path and
            self.platform_str == obj.platform_str and
            self.build_dir == obj.build_dir)

  def __ne__(self, obj):
    return not self == obj


class ChromiumOutputPanel:
  panel = None
  panel_lock = threading.Lock()
  window = None

  def __init__(self, window):
    with self.panel_lock:
      self.window = window
      self.panel = window.create_output_panel('chromium_panel')
      settings = self.panel.settings()
      settings.set('result_line_regex', LINE_REGEX)

      settings.set('result_base_dir', "some/dir/i/set")
      self.Show()

  def Print(self, msg):
    with self.panel_lock:
      self.panel.run_command('append', {'characters': msg + "\n"})

  def Show(self):
    self.window.run_command('show_panel', {'panel': 'output.chromium_panel'})


class DeviceInputHandler(sublime_plugin.TextInputHandler):
  def name(self):
    return 'device'

  def placeholder(self):
    if BashInterface.Get().IsChromeSdk():
      return BashInterface.Get().GetChromeSdkBoard()
    return ""


  OPERATION_LIST = [
    ("Generate GN Args", Operation.GENERATE_GN_ARGS),
    ("Build", Operation.BUILD),
    ("Run", Operation.RUN),
    ("Deploy", Operation.DEPLOY),
    ("Build & Run", Operation.BUILD_AND_RUN),
    ("Build & Deploy", Operation.BUILD_AND_DEPLOY),
  ]

  MESSAGES = [
    "Generate GN args for the selected platform.",
    "Build chrome binary for the given platform.",
    "Run the most recently built chrome binary",
    "Deploy the most recently built chrome binary on a device.",
    "Build and run the new binary for the selected platform.",
    "Build and deploy the new binary onto a device.",
  ]

  # Indices of operations not supported by the current platform. This list is in
  # reverse order to ensure iterative deletion is correct.
  UNSUPPORTED_OPERATION_INDEX = [
    [4, 2],     # android
    [5, 3],     # chrome os
    [4, 2],     # chrome os device
    [5, 3]      # linux
  ]

  platform = None
  operations = []

  def __init__(self, platform):
    self.platform = platform['platform']

    print (self.OPERATION_LIST)
    print (self.platform)
    self.operations = self.OPERATION_LIST.copy()
    for index in self.UNSUPPORTED_OPERATION_INDEX[self.platform]:
      print ("Deleting index " + str(index))
      del self.operations[index]

  def name(self):
    return "operation"

  def list_items(self):
    return self.operations

  def preview(self, value):
    print (value)
    return self.MESSAGES[value]

  def next_input(self, args):
    if self.platform is Platform.CHROME_OS_DEVICE:
      return DeviceInputHandler()
    return None


class PlatformOptionInputHandler(sublime_plugin.ListInputHandler):
  PLATFORM_LIST = [
    ("Android", Platform.ANDROID),
    ("Chrome OS", Platform.CHROME_OS),
    ("Chrome OS (Device)", Platform.CHROME_OS_DEVICE),
    ("Linux", Platform.LINUX)
  ]

  def name(self):
    return "platform"

  def list_items(self):
    return self.PLATFORM_LIST

  def preview(self, value):
    return self.description(value, self.PLATFORM_LIST[value][0])

  def next_input(self, args):
    return OperationOptionInputHandler(args)

  def description(self, value, text):
    return "Build chromium for " + str(text) + "."

class GnArgViewListener(sublime_plugin.ViewEventListener):
  out_dir = None
  def __init__(self, view):
    super().__init__(view)
    print ("Init")
    self.out_dir = self.view.settings().get(GN_ARGS_OUT_DIR_KEY)
    print ("Out directory received: " + str(self.out_dir))


  def is_applicable(settings):
    return settings.has(GN_ARGS_FILE_KEY)

  def on_close(self):
    if self.out_dir is None:
      print ("Out director was NONE!")
      return
    if not os.path.exists(self.out_dir):
      print ("Path did not exist: " + self.out_dir)
      BashInterface.Get().CreateDirectory(self.out_dir)
    else:
      print ("Path exists: " + self.out_dir)

    target_gn_file = self.out_dir + GN_ARGS_FILE_NAME
    BashInterface.Get().CopyFileContents(self.view.file_name(), target_gn_file)

    BashInterface.Get().GenerateGnArgs(self.out_dir)



class ChromiumCommand(sublime_plugin.WindowCommand):
  panel = None
  platform_input = None
  previous_args = None
  output_panel = None
  is_repeat = False

  def __init__(self, *args):
    super(ChromiumCommand, self).__init__(*args)

    # Ensure we are in the correct project directory
    project_src_path = self.window.extract_variables()['folder']
    BashInterface.Get().GoToDirectory(project_src_path)

  def is_enabled(self):
    return True

  def run(self, **args):
    print (args)
    if not self.output_panel:
      self.output_panel = ChromiumOutputPanel(self.window)

    if args['operation'] in [Operation.SHOW_OUTPUT_PANEL]:
      self.output_panel.Show()
      return

    if args['operation'] in [Operation.REPEAT_PREVIOUS_OPERATION]:
      if self.previous_args:
        args = self.previous_args
      else:
        self.output_panel.Print("No previous operation available.")
    else:
      self.previous_args = args

    BashInterface.Get().SetOutputPanel(self.output_panel)

    build_settings = BuildSettings(self.window, args)

    if args['operation'] == Operation.GENERATE_GN_ARGS:
      self.GenerateGnArgs(build_settings)
      return


    if args['operation'] in [Operation.BUILD,
                             Operation.BUILD_AND_RUN,
                             Operation.BUILD_AND_DEPLOY]:
      self.Build(build_settings)
    if args['operation'] in [Operation.RUN, Operation.BUILD_AND_RUN]:
      self.Run(build_settings)
    if args['operation'] in [Operation.DEPLOY, Operation.BUILD_AND_DEPLOY]:
      self.Deploy(build_settings)

  def description(self):
    return 'Build, compile or run chrome.'

  def input(self, args):
    # All the input is already present if this is a repeat operation.
    if 'operation' in args and args['operation'] in [Operation.REPEAT_PREVIOUS_OPERATION]:
      return None
    return PlatformOptionInputHandler()

  def GenerateGnArgs(self, build_settings):
    self.output_panel.Print("Generating GN Args")
    self.output_panel.Print("Project path: " + build_settings.project_src_path)
    self.output_panel.Print("out directory: " + build_settings.build_dir)

    source_gn_dir = build_settings.project_path + "/"
    source_gn_file = build_settings.platform_str + '.gn'

    BashInterface.Get().MaybeCreateFile(source_gn_dir, source_gn_file)

    gn_view = self.window.open_file(
         source_gn_dir + source_gn_file, sublime.TRANSIENT)
    gn_view.settings().set(GN_ARGS_FILE_KEY, True)
    gn_view.settings().set(GN_ARGS_OUT_DIR_KEY, build_settings.build_dir)
    gn_view.settings().set(GN_ARGS_SOURCE_FILE_KEY, source_gn_file)

  def Build(self, build_settings):
    self.output_panel.Print("Build chrome for " + build_settings.platform_str)
    self.output_panel.Print("Targets: " + (",".join(build_settings.targets)))
    BashInterface.Get().Build(build_settings)

  def Run(self, build_settings):
    self.output_panel.Print("Executing chrome for " + build_settings.platform_str)
    BashInterface.Get().Run(build_settings)
