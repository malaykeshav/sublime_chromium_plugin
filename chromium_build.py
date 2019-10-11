import sublime
import sublime_plugin

import select
import subprocess
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

GN_ARGS_FILE_NAME = "args.gn"

# Bash command line interface for this plugin.
BASH_INTERFACE = None

LINE_REGEX = r'(?:^|[)] )[.\\\\/]*([a-z]?:?[\\w.\\\\/]+)[(:]([0-9]+)[,:]?([0-9]+)?[)]?:?(.*)$'

# Settings key:
GN_ARGS_FILE_KEY = 'GN_ARGS_FILE_KEY'
GN_ARGS_OUT_DIR_KEY = 'GN_ARGS_OUT_DIR_KEY'

class BashInterface:
  output_panel = None
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
    self.BASH.stdin.write(bytes(cmd, 'UTF-8'))
    self.BASH.stdin.flush()

  def __GetResult(self, timeout=0.5):
    result = ""

    r, w, e = select.select([self.BASH.stdout], [], [], timeout)
    while self.BASH.stdout in r:
      result += os.read(self.BASH.stdout.fileno(), 10).decode("utf-8")
      r, w, e = select.select([self.BASH.stdout], [], [], 0.5)

    return result

  def __StreamResult(self, timeout=0.5):
    threading.Thread(
        target=self.__StreamResultTarget,
        args=(self.BASH.stdout, timeout, self.output_panel)).start()


  def __StreamResultTarget(self, stdout, timeout, output_panel):
    result = ""
    r, w, e = select.select([stdout], [], [], timeout)
    while self.BASH.stdout in r:
      result += os.read(stdout.fileno(), 2**8).decode("utf-8")
      r, w, e = select.select([stdout], [], [], 0.5)
    if output_panel:
      output_panel.Print(result)
      print (result)
    else:
      print (result)

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

  def CreateDirectory(self, path):
    self.__RunCmd("mkdir -p " + path)

  def GenerateGnArgs(self, path):
    print ("Will run: " + "gn gen \'" + path + "\'\n")
    self.__RunCmd("gn gen \'" + path + "\'\n")
    self.output_panel.Print("gn gen \'" + path)
    self.__StreamResult(10)

  def GoToDirectory(self, path):
    self.__RunCmd("cd " + path + "\n")
    self.__StreamResult(1)

  def SetOutputPanel(self, output_panel):
    self.output_panel = output_panel

class ChromiumOutputPanel:
  panel = None
  panel_lock = threading.Lock()

  def __init__(self, window):
    with self.panel_lock:
      self.panel = window.create_output_panel('exec')
      settings = self.panel.settings()
      settings.set('result_line_regex', LINE_REGEX)

      settings.set('result_base_dir', "some/dir/i/set")
      window.run_command('show_panel', {'panel': 'output.exec'})

  def Print(self, msg):
    with self.panel_lock:
      self.panel.run_command('append', {'characters': msg + "\n"})


class DeviceInputHandler(sublime_plugin.TextInputHandler):
  def name(self):
    return 'device'

  def placeholder(self):
    if BashInterface.Get().IsChromeSdk():
      return BashInterface.Get().GetChromeSdkBoard()
    return ""


class OperationOptionInputHandler(sublime_plugin.ListInputHandler):
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
    print ("Path exists: " + self.out_dir)
    if not os.path.exists(self.out_dir):
      BashInterface.Get().CreateDirectory(self.out_dir)
    print ("Path exists: " + self.out_dir + GN_ARGS_FILE_NAME)
    if not os.path.exists(self.out_dir + GN_ARGS_FILE_NAME):
      BashInterface.Get().MaybeCreateFile(self.out_dir, GN_ARGS_FILE_NAME)

    BashInterface.Get().GenerateGnArgs(self.out_dir)
    print ("Now generate gn args")



class ChromiumCommand(sublime_plugin.WindowCommand):
  panel = None
  platform_input = None
  previous_config = None
  output_panel = None

  def __init__(self, *args):
    super(ChromiumCommand, self).__init__(*args)

    # Ensure we are in the correct project directory
    project_path = self.window.extract_variables()['folder']
    BashInterface.Get().GoToDirectory(project_path)

  def is_enabled(self):
    return True

  def run(self, **args):
    print (args)
    self.output_panel = ChromiumOutputPanel(self.window)
    BashInterface.Get().SetOutputPanel(self.output_panel)

    if args['operation'] == Operation.GENERATE_GN_ARGS:
      self.GenerateGnArgs(args)
      return
    if previous_config == args:
      self.Build(args)
      return
    previous_config = args

    # self.panel = self.window.create_output_panel("exec")
    # self.window.run_command("show_panel", {"panel": "output.exec"})
    # self.panel.run_command("append", {"characters": "Hello. Now Building. Okay"})
    return

  def description(self):
    return 'Build, compile or run chrome.'

  def input(self, args):
    return PlatformOptionInputHandler()

  def GenerateGnArgs(self, args):
    self.output_panel.Print("Generating GN Args")
    project_path = self.window.extract_variables()['folder']
    self.output_panel.Print("Project path: " + project_path)
    platform = args['platform']

    if "device" not in args:
      args["device"] = ""

    platform_token = ['android', 'cros', args["device"], 'linux'][platform]
    out_dir = project_path + '/out_' + platform_token + '/Default/'
    self.output_panel.Print("out directory: " + out_dir)

    source_gn_dir = project_path + "/"
    source_gn_file = platform_token + '.gn'

    BashInterface.Get().MaybeCreateFile(source_gn_dir, source_gn_file)

    gn_view = self.window.open_file(
         source_gn_dir + source_gn_file, sublime.TRANSIENT)
    gn_view.settings().set(GN_ARGS_FILE_KEY, True)
    gn_view.settings().set(GN_ARGS_OUT_DIR_KEY, out_dir)


class ChromiumBuildCommand(sublime_plugin.WindowCommand):
  def is_enabled(self):
    return True

  def run(self):
    return
