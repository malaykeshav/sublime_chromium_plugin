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

# Settings key:
GN_ARGS_FILE_KEY = 'GN_ARG_FILE_VIEW'

class BashInterface:
  def Get():
    global BASH_INTERFACE
    if BASH_INTERFACE is None:
      BASH_INTERFACE = BashInterface()
    return BASH_INTERFACE

  def __init__(self):
    self.BASH = subprocess.Popen(['/bin/bash'], shell=True,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

  def __RunCmd(self, cmd):
    self.BASH.stdin.write(bytes(cmd, 'UTF-8'))
    self.BASH.stdin.flush()

  def __GetResult(self):
    result = ""
    
    r, w, e = select.select([self.BASH.stdout], [], [], 0.5)
    while self.BASH.stdout in r:
      result += os.read(self.BASH.stdout.fileno(), 10).decode("utf-8")
      r, w, e = select.select([self.BASH.stdout], [], [], 0.5)

    return result

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
  def __init__(self, view, out_dir):
    super().__init__(view)
    self.platform_token = platform_token
    self.out_dir = out_dir

  def is_applicable(settings):
    return settings.has(GN_ARGS_FILE_KEY)

  def on_close(self):
    if not os.path.exists(self.out_dir):
      BashInterface.Get().CreateDirectory(self.out_dir)
    if not os.path.exists(self.out_dir + GN_ARGS_FILE_NAME):
      BashInterface.Get().MaybeCreateFile(self.out_dir, GN_ARGS_FILE_NAME)
    print ("Now generate gn args")



class ChromiumCommand(sublime_plugin.WindowCommand):
  panel = None
  platform_input = None
  previous_config = None

  def is_enabled(self):
    return True

  def run(self, **args):
    print (args)
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
    project_path = self.window.extract_variables()['folder']
    platform = args['platform']

    if "device" not in args:
      args["device"] = ""

    platform_token = ['android', 'cros', args["device"], 'linux'][platform]
    out_dir = project_path + '/out_' + platform_token + '/Default'

    source_gn_dir = project_path + "/"
    source_gn_file = platform_token + '.gn'

    BashInterface.Get().MaybeCreateFile(source_gn_dir, source_gn_file)

    gn_view = self.window.open_file(
         source_gn_dir + source_gn_file, sublime.TRANSIENT)
    gn_view.settings().set(GN_ARGS_FILE_KEY, True)

    listener = GnArgViewListener(gn_view, platform_token, out_dir)

class ChromiumBuildCommand(sublime_plugin.WindowCommand):
  def is_enabled(self):
    return True

  def run(self):
    return