
import sys, os, importlib, logging, time

logger = logging.getLogger("plugin_bridge")

_PLUGINS_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "plugins"))
if _PLUGINS_DIR not in sys.path:
    sys.path.insert(0, _PLUGINS_DIR)

_plugins = {}       # name -> module
_mtimes = {}        # name -> file mtime

def _get_mtime(name):
    path = os.path.join(_PLUGINS_DIR, f"{name}.py")
    try: return os.path.getmtime(path)
    except: return 0
#load
def load_all():
    global _plugins, _mtimes
    if not os.path.isdir(_PLUGINS_DIR):
        return
    for fname in sorted(os.listdir(_PLUGINS_DIR)):
        if not fname.endswith(".py") or fname.startswith("_"):
            continue
        name = fname[:-3]
        try:
            if name in _plugins:
                _plugins[name] = importlib.reload(_plugins[name])
            else:
                _plugins[name] = importlib.import_module(name)
            _mtimes[name] = _get_mtime(name)
            info = getattr(_plugins[name], "PLUGIN_INFO", {"name": name})
            logger.info(f"Plugin loaded: {info.get('name', name)} v{info.get('version', '?')}")
        except Exception as e:
            logger.warning(f"Plugin load failed: {name}: {e}")
#hot update
def hot_check():
    for name in list(_plugins.keys()):
        mtime = _get_mtime(name)
        if mtime > _mtimes.get(name, 0):
            try:
                _plugins[name] = importlib.reload(_plugins[name])
                _mtimes[name] = mtime
                logger.info(f"Plugin hot-reloaded: {name}")
            except Exception as e:
                logger.warning(f"Plugin reload failed: {name}: {e}")
#upd
def get(name):
    hot_check()
    return _plugins.get(name)
#listfun
def list_all():
    hot_check()
    result = {}
    for name, mod in _plugins.items():
        info = getattr(mod, "PLUGIN_INFO", {"name": name})
        funcs = [x for x in dir(mod) if not x.startswith("_") and callable(getattr(mod, x, None))]
        result[name] = {"info": info, "functions": funcs[:30]}
    return result
#callfun
def call(plugin, func, *args, **kwargs):
    mod = get(plugin)
    if not mod:
        raise ImportError(f"Plugin not found: {plugin}")
    fn = getattr(mod, func, None)
    if not fn:
        raise AttributeError(f"Plugin {plugin} has no function {func}")
    return fn(*args, **kwargs)

# 启动时自动加载所有插件
load_all()
