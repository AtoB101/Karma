"""让 ``import karma_mcp_server`` 在未安装时也能工作。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
