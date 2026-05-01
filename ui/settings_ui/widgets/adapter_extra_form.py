"""根据适配器 get_config_schema() 构建简单的额外配置表单控件。"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QSpinBox,
    QWidget,
)


def _truthy(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    s = str(v).strip().lower()
    return s in ("1", "true", "yes", "on")


def build_schema_widgets(
    schema: dict[str, dict],
    values: dict[str, Any],
    parent: QWidget | None,
) -> tuple[QWidget, dict[str, QWidget]]:
    """根据 schema 创建表单；返回 (容器, 字段 key -> 编辑器 widget)。"""
    wrap = QWidget(parent)
    wrap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
    form = QFormLayout(wrap)
    form.setContentsMargins(0, 0, 0, 0)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
    form.setVerticalSpacing(10)
    editors: dict[str, QWidget] = {}

    for key, meta in schema.items():
        label_text = str(meta.get("label", key))
        typ = str(meta.get("type", "str")).lower()
        default = meta.get("default", "")
        cur = values.get(key, default)

        lab = QLabel(label_text)
        lab.setWordWrap(True)
        lab.setMinimumWidth(80)
        choices = meta.get("choices")
        if isinstance(choices, (list, tuple)) and choices:
            combo = QComboBox()
            for opt in choices:
                sopt = str(opt)
                combo.addItem(sopt, sopt)
            combo.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            cur_s = str(cur if cur is not None else default)
            idx = combo.findData(cur_s)
            if idx < 0:
                idx = combo.findData(str(default))
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            form.addRow(lab, combo)
            editors[key] = combo
        elif typ == "bool":
            cb = QCheckBox()
            cb.setChecked(_truthy(cur))
            form.addRow(lab, cb)
            editors[key] = cb
        elif typ == "int":
            sp = QSpinBox()
            mn = meta.get("min")
            mx = meta.get("max")
            if mn is not None and mx is not None:
                sp.setRange(int(mn), int(mx))
            else:
                sp.setRange(-2147483648, 2147483647)
            try:
                sp.setValue(int(cur))
            except (TypeError, ValueError):
                sp.setValue(int(default) if default != "" else 0)
            form.addRow(lab, sp)
            editors[key] = sp
        elif typ == "float":
            dsp = QDoubleSpinBox()
            step = float(meta.get("step", 0.01) or 0.01)
            dsp.setDecimals(max(2, len(str(step).split(".")[-1]) if "." in str(step) else 2))
            dsp.setSingleStep(step)
            mn = meta.get("min")
            mx = meta.get("max")
            lo = float(mn) if mn is not None else -1e9
            hi = float(mx) if mx is not None else 1e9
            dsp.setRange(lo, hi)
            try:
                dsp.setValue(float(cur))
            except (TypeError, ValueError):
                dsp.setValue(float(default) if default != "" else 0.0)
            form.addRow(lab, dsp)
            editors[key] = dsp
        else:
            le = QLineEdit("" if cur is None else str(cur))
            le.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            if _truthy(meta.get("secret")):
                le.setEchoMode(QLineEdit.EchoMode.Password)
            form.addRow(lab, le)
            editors[key] = le

    return wrap, editors


def read_schema_values(schema: dict[str, dict], editors: dict[str, QWidget]) -> dict[str, Any]:
    """从编辑器读取与 schema 类型一致的 Python 值。"""
    out: dict[str, Any] = {}
    for key, meta in schema.items():
        w = editors.get(key)
        if w is None:
            continue
        typ = str(meta.get("type", "str")).lower()
        default = meta.get("default", "")
        if typ == "bool" and isinstance(w, QCheckBox):
            out[key] = w.isChecked()
        elif typ == "int" and isinstance(w, QSpinBox):
            out[key] = int(w.value())
        elif typ == "float" and isinstance(w, QDoubleSpinBox):
            out[key] = float(w.value())
        elif isinstance(w, QComboBox):
            d = w.currentData()
            out[key] = str(d) if d is not None else str(w.currentText())
        elif isinstance(w, QLineEdit):
            raw = w.text().strip()
            if typ == "int":
                try:
                    out[key] = int(raw) if raw else int(default)
                except (TypeError, ValueError):
                    out[key] = int(default) if default != "" else 0
            elif typ == "float":
                try:
                    out[key] = float(raw) if raw else float(default)
                except (TypeError, ValueError):
                    out[key] = float(default) if default != "" else 0.0
            else:
                out[key] = raw if raw else str(default)
        else:
            out[key] = default
    return out
