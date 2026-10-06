# 包装器契约测试（离线，2026-10-06 复审）：不装官方包、不打网络，用伪
# cellphonedb 模块（签名照抄官方 v5.0.1 call 参数表）锁定 driver → 官方
# API 的参数传递契约。
#
# 固化的 v1 缺陷：driver 读 CPDB_SEED 却传名为 `seed` 的参数——官方签名
# 里不存在，被签名过滤静默删除（dropped_unsupported 打了日志但种子从未
# 生效，实际 debug_seed=-1、threads=4）。修复契约：设种子 → 传官方参数名
# debug_seed 且钉 threads=1（官方 testing-only 种子唯一受支持的生效模式）；
# 未设/-1 → 两者都不传，保持官方默认。不宣称多线程置换可复现。
import importlib.metadata
import importlib.util
import inspect
import json
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DRIVER = REPO / "driver.py"

# 官方 v5.0.1 cpdb_statistical_analysis_method.call 的参数表（照抄源码，
# 参数名是本测试的被测契约，一个都不能少——签名过滤按它删参数）。
OFFICIAL_CALL_PARAMS = [
    "cpdb_file_path", "meta_file_path", "counts_file_path", "counts_data",
    "output_path", "microenvs_file_path", "active_tfs_file_path",
    "iterations", "threshold", "threads", "debug_seed", "result_precision",
    "pvalue", "subsampling", "subsampling_log", "subsampling_num_pc",
    "subsampling_num_cells", "separator", "debug", "output_suffix",
    "score_interactions",
]


def install_fake_cpdb(record):
    # 注册伪模块树 cellphonedb.src.core.methods.cpdb_statistical_analysis_
    # method：call 带**官方显式签名**（driver 的签名过滤读
    # inspect.signature(call)，**kwargs 伪签名会让所有参数被删）。
    stat = types.ModuleType(
        "cellphonedb.src.core.methods.cpdb_statistical_analysis_method")

    def call(**kwargs):
        record.update(kwargs)
        # 官方输出带运行时间戳；写一个让改名契约路径真实执行。
        out = Path(kwargs["output_path"])
        out.mkdir(parents=True, exist_ok=True)
        (out / "statistical_analysis_pvalues_10_06_2026_123456.txt").write_text(
            "fake", encoding="utf-8")
        return {"relevant_interactions": []}

    call.__signature__ = inspect.Signature(
        [inspect.Parameter(p, inspect.Parameter.POSITIONAL_OR_KEYWORD)
         for p in OFFICIAL_CALL_PARAMS]
    )
    stat.call = call

    modules = {}
    names = ["cellphonedb", "cellphonedb.src", "cellphonedb.src.core",
             "cellphonedb.src.core.methods"]
    for name in names:
        modules[name] = types.ModuleType(name)
    for parent, child in zip(names, names[1:] + [stat.__name__]):
        setattr(modules[parent], child.split(".")[-1],
                modules.get(child, stat))
    for name, module in list(modules.items()) + [(stat.__name__, stat)]:
        sys.modules[name] = module
    return list(modules) + [stat.__name__]


def load_driver():
    spec = importlib.util.spec_from_file_location("cpdb_driver", DRIVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fake_cpdb(monkeypatch):
    record = {}
    installed = install_fake_cpdb(record)
    monkeypatch.setattr(importlib.metadata, "version",
                        lambda name: "5.0.1-fake", raising=True)
    yield record
    for name in installed:
        sys.modules.pop(name, None)


@pytest.fixture
def run_driver(fake_cpdb, tmp_path, monkeypatch):
    def _run(extra_env=None):
        counts = tmp_path / "counts.h5ad"
        counts.write_text("dummy", encoding="utf-8")  # 只作路径传递（meta 已提供）
        meta = tmp_path / "meta.tsv"
        meta.write_text("Cell\tcluster\nc1\tA\nc2\tB\n", encoding="utf-8")
        root = tmp_path / "cpdbroot"
        root.mkdir()
        (root / "cellphonedb.zip").write_bytes(b"fake-zip")
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        for key in ("CPDB_SEED",):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("AUTONOMICS_INPUT0", str(counts))
        monkeypatch.setenv("AUTONOMICS_INPUT1", str(meta))
        monkeypatch.setenv("AUTONOMICS_WORKDIR", str(out_dir))
        monkeypatch.setenv("CPDB_ROOT", str(root))
        for key, value in (extra_env or {}).items():
            monkeypatch.setenv(key, value)
        driver = load_driver()
        driver.main()
        return fake_cpdb, out_dir

    return _run


def test_seed_set_passes_official_debug_seed_and_pins_single_thread(run_driver):
    # 修复契约：CPDB_SEED=123 → 官方参数名 debug_seed=123 且 threads=1。
    # v1 缺陷在此必挂：传 `seed` 被签名过滤删除 → record 无 debug_seed、
    # 无 threads（实际 debug_seed=-1、threads=4，种子从未生效）。
    record, out_dir = run_driver({"CPDB_SEED": "123"})
    assert record.get("debug_seed") == 123
    assert record.get("threads") == 1
    assert "seed" not in record  # 不存在名为 seed 的官方参数
    provenance = json.loads((out_dir / "cpdb_provenance.json").read_text())
    assert provenance["params"]["debug_seed"] == "123"
    assert provenance["params"]["threads"] == "1"


def test_seed_absent_keeps_official_defaults(run_driver):
    # 未设种子 → debug_seed/threads 都不传（官方默认 -1 / 4），
    # p 值跨次运行有 1/iterations 粒度波动——继承的官方行为。
    record, out_dir = run_driver()
    assert "debug_seed" not in record
    assert "threads" not in record
    provenance = json.loads((out_dir / "cpdb_provenance.json").read_text())
    assert "debug_seed" not in provenance["params"]
    assert "threads" not in provenance["params"]


def test_seed_minus_one_is_official_unset_sentinel(run_driver):
    # CPDB_SEED=-1 = 官方"未设"哨兵 → 与不传等价。
    record, _ = run_driver({"CPDB_SEED": "-1"})
    assert "debug_seed" not in record
    assert "threads" not in record


def test_timestamped_output_renamed_to_stable_contract(run_driver):
    # 改名契约仍在：statistical_analysis_*_<ts>.txt → cpdb_pvalues.txt。
    _, out_dir = run_driver()
    assert (out_dir / "cpdb_pvalues.txt").read_text(encoding="utf-8") == "fake"
