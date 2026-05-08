import os
import importlib

class RoleManager:

    def __init__(self):
        self.roles = {}

    def register(self, role_class):
        self.roles[role_class.name] = role_class

    def load_roles(self):

        base_folder = "roles"

        for root, dirs, files in os.walk(base_folder):
            for file in files:
                if file.endswith(".py") and file not in (
                    "__init__.py",
                    "role_manager.py",
                    "base_role.py"
                ):
                    module_path = os.path.join(root, file)
                    module_name = module_path.replace("/", ".").replace("\\", ".")[:-3]

                    module = importlib.import_module(module_name)

                    if hasattr(module, "register_role"):
                        module.register_role(self)

        print("Loaded roles:", list(self.roles.keys()))
