from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from lidar_label_tool.io.dataset_v2 import load_dataset_manifest_v2
from lidar_label_tool.services.label_migration_v2 import (
    LabelMigrationPlan, LabelMigrationRequest, LabelMigrationResult,
    analyze_label_migration_v2, migrate_labels_v2, parse_class_mapping,
)
from lidar_label_tool.ui.task_dialog import run_task


class LabelMigrationV2Dialog(QDialog):
    """Explicit mapping and preview; all file parsing/writing belongs to the service."""

    def __init__(self, config_root: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config_root = Path(config_root).resolve()
        self.plan: LabelMigrationPlan | None = None
        self.migration_result: LabelMigrationResult | None = None
        manifest = load_dataset_manifest_v2(self.config_root)
        self.setWindowTitle("v1 작업 라벨 전체 frame → v2 이관")
        self.resize(800, 640)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "먼저 구성된 v2 profile을 선택하세요. 같은 dataset·LiDAR·좌표계·point binding을 "
            "증명할 수 있는 저장된 v1 라벨만 새 namespace로 이관합니다. 원본 JSON/.bak과 "
            "dataset.json은 변경하지 않으며 v1 recovery는 이관하지 않습니다."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        form.addRow("v2 구성 폴더", QLabel(str(self.config_root)))
        self.profile_combo = QComboBox()
        for profile in manifest.profiles:
            self.profile_combo.addItem(f"{profile.display_name} ({profile.id})", profile.id)
        self.profile_combo.setCurrentIndex(self.profile_combo.findData(manifest.default_profile_id))
        self.profile_combo.currentIndexChanged.connect(self._invalidate)
        form.addRow("대상 profile", self.profile_combo)
        self.source_labels_edit = self._directory_row(form, "v1 작업 라벨 폴더")
        self.source_data_edit = self._directory_row(form, "v1 원본 데이터 루트")
        self.workspace_edit = self._directory_row(form, "외부 workspace (선택)")
        self.legacy_id_edit = QLineEdit()
        self.legacy_id_edit.setPlaceholderText("ID가 다를 때만: manifest metadata의 legacy_dataset_id와 동일한 값")
        self.legacy_id_edit.textChanged.connect(self._invalidate)
        form.addRow("기존 dataset ID (선택)", self.legacy_id_edit)
        layout.addLayout(form)
        mapping_label = QLabel("명시적인 class mapping: 한 줄에 원본 class_name = 대상 class_id (예: Car = car)")
        mapping_label.setWordWrap(True)
        layout.addWidget(mapping_label)
        self.mapping_edit = QPlainTextEdit()
        self.mapping_edit.setPlaceholderText("car = car\npedestrian = pedestrian\nsign = sign")
        self.mapping_edit.setMaximumHeight(130)
        self.mapping_edit.textChanged.connect(self._invalidate)
        layout.addWidget(self.mapping_edit)
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setPlaceholderText("‘전체 frame 분석’을 누르면 파일 수·객체 수·대상 경로를 미리 확인할 수 있습니다.")
        layout.addWidget(self.summary, 1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.analyze_button = self.buttons.addButton("전체 frame 분석", QDialogButtonBox.ButtonRole.ActionRole)
        self.apply_button = self.buttons.addButton("확인 후 전체 이관", QDialogButtonBox.ButtonRole.ActionRole)
        self.apply_button.setEnabled(False)
        self.analyze_button.clicked.connect(self._analyze)
        self.apply_button.clicked.connect(self._apply)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def _directory_row(self, form: QFormLayout, title: str) -> QLineEdit:
        edit = QLineEdit()
        edit.textChanged.connect(self._invalidate)
        browse = QPushButton("찾기…")
        browse.clicked.connect(lambda: self._choose_directory(edit, title))
        row = QHBoxLayout()
        row.addWidget(edit, 1)
        row.addWidget(browse)
        form.addRow(title, row)
        return edit

    def _choose_directory(self, edit: QLineEdit, title: str) -> None:
        directory = QFileDialog.getExistingDirectory(self, title, edit.text() or str(self.config_root))
        if directory:
            edit.setText(directory)

    def _invalidate(self) -> None:
        self.plan = None
        if hasattr(self, "apply_button"):
            self.apply_button.setEnabled(False)

    def _request(self) -> LabelMigrationRequest:
        if not self.source_labels_edit.text().strip() or not self.source_data_edit.text().strip():
            raise ValueError("v1 작업 라벨 폴더와 원본 데이터 루트를 모두 선택하세요.")
        workspace = self.workspace_edit.text().strip()
        return LabelMigrationRequest(
            config_root=self.config_root,
            source_annotation_dir=Path(self.source_labels_edit.text().strip()),
            source_data_root=Path(self.source_data_edit.text().strip()),
            profile_id=str(self.profile_combo.currentData()),
            class_mapping=parse_class_mapping(self.mapping_edit.toPlainText()),
            workspace_root=Path(workspace) if workspace else None,
            legacy_dataset_id=self.legacy_id_edit.text().strip() or None,
        )

    def _analyze(self) -> None:
        self._invalidate()
        try:
            request = self._request()
            plan = run_task(self, "v1 전체 frame 이관 분석", lambda task: analyze_label_migration_v2(request, task=task))
        except Exception as exc:
            QMessageBox.warning(self, "이관 분석 중단", str(exc))
            return
        if plan is None:
            return
        self.plan = plan
        lines = [
            f"Dataset: {plan.source_dataset_id} → {plan.dataset_id}",
            f"Profile / LiDAR: {plan.profile_id} / {plan.label_lidar_id}",
            f"Frame {len(plan.frames)}개 · 객체 {plan.object_count}개",
            f"대상: {plan.target_namespace}",
            "Revision: 각 원본 revision + 1", "좌표/크기/yaw/객체 ID: 유지", "",
        ]
        lines.extend(f"{source} → {target}" for source, target in request.class_mapping.items())
        lines.extend(["", "이미 완료된 동일 이관입니다. 재작성하지 않습니다." if plan.already_migrated
                      else "전체 검증 통과. 적용 전까지 파일은 변경되지 않았습니다.",
                      "카메라/보정 context는 대상 profile 기준이므로 이관 후 재검토하세요."])
        self.summary.setPlainText("\n".join(lines))
        self.apply_button.setEnabled(True)

    def _apply(self) -> None:
        plan = self.plan
        if plan is None:
            return
        answer = QMessageBox.question(
            self, "전체 frame 이관 확인",
            f"검증한 {len(plan.frames)}개 frame의 class mapping을 확인했으며\n"
            f"다음 namespace로 이관할까요?\n{plan.target_namespace}\n\n"
            "기존 대상이 있으면 덮어쓰지 않고 중단합니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            result = run_task(self, "v1 → v2 전체 이관", lambda task: migrate_labels_v2(plan, confirmed=True, task=task))
        except Exception as exc:
            self._invalidate()
            QMessageBox.critical(self, "이관 중단", f"{exc}\n\n원본 라벨은 보존됩니다. 다시 분석하세요.")
            return
        if result is None:
            self._invalidate()
            return
        self.migration_result = result
        QMessageBox.information(
            self, "이관 완료",
            f"{result.status}: {result.frame_count}개 frame\n보고서: {result.report_path}"
            + ("\n\n" + "\n".join(result.warnings) if result.warnings else ""),
        )
        self.accept()
