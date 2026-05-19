from PyQt6.QtWidgets import (
    QWidget, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QMessageBox,
    QTabWidget, QFormLayout,
    QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit,
)
from PyQt6.QtCore import Qt, QTimer

import database
from keyboard import install_keyboard
from utils import screen_size
from dialogs import (
    ActualTransactionDialog,
    DataCollectionDialog,
    HardwareTestDialog,
    WeightSensorTestDialog,
    CoinDispenserDialog,
)


class MainWindow(QWidget):
    """Top-level application window with role-based tabbed interface.

    Roles:
        admin — New Transaction, History, Admin Settings
        user  — New Transaction only
    """

    def __init__(self, username: str, role: str = "user"):
        super().__init__()
        self.username = username
        self.role = role
        self.setWindowTitle("RTL Junkshop System")
        self.showFullScreen()

        SW, _ = screen_size()
        scale = SW / 800

        self._scale = scale
        self._apply_stylesheet(scale)
        self._build_ui(scale)
        self.load_transaction_history()

        if self.role == "admin":
            install_keyboard(
                self,
                numeric_inputs={self.pet_price_input, self.metal_price_input},
            )

    # ── Stylesheet ───────────────────────────────────────────────────────────

    def _apply_stylesheet(self, scale: float):
        self.setStyleSheet(f"""
            QWidget {{
                font-family: 'Arial';
                font-size: {max(11, int(13*scale))}px;
            }}
            QPushButton {{
                padding: 4px;
                border-radius: 6px;
            }}
            QTabWidget::pane {{
                border: 1px solid #ccc;
                top: -1px;
            }}
            QTabBar::tab {{
                height: {max(32, int(40*scale))}px;
                width:  {max(100, int(130*scale))}px;
                font-size: {max(11, int(13*scale))}px;
                background: #f0f0f0;
            }}
            QTabBar::tab:selected {{
                background: #ffffff;
                font-weight: bold;
            }}
            QLineEdit {{
                height: {max(28, int(35*scale))}px;
                font-size: {max(13, int(16*scale))}px;
            }}
        """)

    # ── UI ───────────────────────────────────────────────────────────────────

    def _build_ui(self, scale: float):
        fs_large = max(16, int(22 * scale))
        fs_med   = max(13, int(18 * scale))
        btn_h_lg = max(80, int(130 * scale))
        btn_h_sm = max(40, int(55 * scale))

        self.tabs = QTabWidget()
        self.tabs.addTab(
            self._build_transaction_tab(scale, fs_large, fs_med, btn_h_lg, btn_h_sm),
            "New Transaction",
        )

        # History and Admin Settings are admin-only
        if self.role == "admin":
            self.tabs.addTab(
                self._build_history_tab(scale, fs_med, btn_h_sm),
                "History",
            )
            self.tabs.addTab(
                self._build_settings_tab(scale, fs_med, btn_h_sm),
                "Admin Settings",
            )

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.addWidget(self.tabs)
        self.setLayout(main_layout)

    def _build_transaction_tab(
        self, scale, fs_large, fs_med, btn_h_lg, btn_h_sm
    ) -> QWidget:
        tab    = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(int(8 * scale))

        heading = QLabel("Select material to sell:")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading.setStyleSheet(
            f"font-size: {fs_large}px; font-weight: bold; margin-bottom: 8px;"
        )
        layout.addWidget(heading)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(int(10 * scale))

        for label, color, material in [
            ("PET Bottles",   "#4CAF50", "PET"),
            ("Metallic Cans", "#607D8B", "Metal"),
        ]:
            btn = QPushButton(label)
            btn.setMinimumHeight(btn_h_lg)
            btn.setStyleSheet(
                f"font-size: {fs_large}px; font-weight: bold; "
                f"background-color: {color}; color: white; border-radius: 10px;"
            )
            btn.clicked.connect(lambda checked, m=material: self._start_sorting(m))
            btn_row.addWidget(btn)

        layout.addLayout(btn_row)

        exit_btn = QPushButton("Exit System")
        exit_btn.setMinimumHeight(btn_h_sm)
        exit_btn.setStyleSheet(
            f"font-size: {fs_med}px; font-weight: bold; "
            f"background-color: #f44336; color: white; border-radius: 8px;"
        )
        exit_btn.clicked.connect(self.close)
        layout.addWidget(exit_btn)

        tab.setLayout(layout)
        return tab

    def _build_history_tab(self, scale, fs_med, btn_h_sm) -> QWidget:
        tab    = QWidget()
        layout = QVBoxLayout()

        self.history_table = QTableWidget()
        self.history_table.setColumnCount(5)
        self.history_table.setHorizontalHeaderLabels(
            ["ID", "Date & Time", "Material", "Weight (kg)", "Total (PHP)"]
        )
        self.history_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.history_table.setStyleSheet(
            f"font-size: {max(11, int(14*scale))}px;"
        )
        self.history_table.verticalHeader().setDefaultSectionSize(
            max(30, int(40 * scale))
        )
        layout.addWidget(self.history_table)

        btn_row = QHBoxLayout()

        refresh_btn = QPushButton("Refresh Data")
        refresh_btn.setMinimumHeight(btn_h_sm)
        refresh_btn.setStyleSheet(
            f"font-size: {fs_med}px; font-weight: bold; "
            f"background-color: #FF9800; color: white; border-radius: 8px;"
        )
        refresh_btn.clicked.connect(self.load_transaction_history)
        btn_row.addWidget(refresh_btn)

        sync_btn = QPushButton("Sync Now")
        sync_btn.setMinimumHeight(btn_h_sm)
        sync_btn.setStyleSheet(
            f"font-size: {fs_med}px; font-weight: bold; "
            f"background-color: #1565C0; color: white; border-radius: 8px;"
        )
        sync_btn.clicked.connect(self._trigger_sync)
        btn_row.addWidget(sync_btn)

        layout.addLayout(btn_row)

        self.sync_status_label = QLabel("Sync: checking...")
        self.sync_status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sync_status_label.setStyleSheet(
            f"font-size: {max(11, int(13*scale))}px; color: #555; padding: 4px;"
        )
        layout.addWidget(self.sync_status_label)

        # Update sync status every 10 seconds
        self._sync_timer = QTimer()
        self._sync_timer.timeout.connect(self._update_sync_status)
        self._sync_timer.start(10000)
        self._update_sync_status()

        tab.setLayout(layout)
        return tab

    def _build_settings_tab(self, scale, fs_med, btn_h_sm) -> QWidget:
        tab    = QWidget()
        layout = QFormLayout()
        layout.setSpacing(int(8 * scale))

        label_style = f"font-size: {fs_med}px; font-weight: bold;"

        self.pet_price_input   = QLineEdit()
        self.metal_price_input = QLineEdit()
        self._load_current_prices()

        for row_label, field in [
            ("PET Bottles Price (PHP/kg):",   self.pet_price_input),
            ("Metallic Cans Price (PHP/kg):", self.metal_price_input),
        ]:
            lbl = QLabel(row_label)
            lbl.setStyleSheet(label_style)
            layout.addRow(lbl, field)

        admin_buttons = [
            ("Save New Prices",                     "#2196F3", self._save_prices),
            ("Open Camera for AI Training",         "#673AB7", self._open_data_collection),
            ("Open Hardware Diagnostics",           "#607D8B", self._open_hardware_test),
            ("Open Weight Sensor (Load Cell) Test", "#8D6E63", self._open_weight_test),
            ("Test Coin Dispenser",                 "#00897B", self._open_coin_dispenser),
        ]
        for label, color, slot in admin_buttons:
            btn = QPushButton(label)
            btn.setMinimumHeight(btn_h_sm)
            btn.setStyleSheet(
                f"font-size: {fs_med}px; font-weight: bold; "
                f"background-color: {color}; color: white; "
                f"border-radius: 8px; margin-top: 6px;"
            )
            btn.clicked.connect(slot)
            layout.addRow(btn)

        tab.setLayout(layout)
        return tab

    # ── Data helpers ─────────────────────────────────────────────────────────

    def _load_current_prices(self):
        self.pet_price_input.setText(str(database.get_price("PET")))
        self.metal_price_input.setText(str(database.get_price("Metal")))

    def _save_prices(self):
        try:
            new_pet   = float(self.pet_price_input.text())
            new_metal = float(self.metal_price_input.text())
            database.update_prices(new_pet, new_metal)
            QMessageBox.information(self, "Success", "Prices updated successfully!")
        except ValueError:
            QMessageBox.warning(self, "Error", "Please enter valid numbers for prices.")

    def load_transaction_history(self):
        # No-op for non-admin (history_table won't exist)
        if self.role != "admin":
            return
        records = database.get_all_transactions()
        self.history_table.setRowCount(0)
        for row_idx, row_data in enumerate(records):
            self.history_table.insertRow(row_idx)
            for col_idx, data in enumerate(row_data):
                text = f"{data:.2f}" if col_idx in (3, 4) else str(data)
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() ^ Qt.ItemFlag.ItemIsEditable)
                self.history_table.setItem(row_idx, col_idx, item)

    # ── Transaction flow ─────────────────────────────────────────────────────

    def _start_sorting(self, material: str):
        price_per_kg = database.get_price(material)
        dialog       = ActualTransactionDialog(material, self)

        if dialog.exec():
            final_weight = dialog.get_final_weight()
            if final_weight > 0:
                total_payout = final_weight * price_per_kg
                database.log_transaction(material, final_weight, total_payout)
                self.load_transaction_history()
                self._show_transaction_summary(material, final_weight, total_payout, dialog)
            else:
                QMessageBox.warning(
                    self, "Cancelled", "No weight detected. Transaction cancelled."
                )

    def _show_transaction_summary(
        self, material: str, weight: float, payout: float, dialog
    ):
        # Show summary — dialog stays open while coins dispense
        msg = QMessageBox(self)
        msg.setWindowTitle("Transaction Complete")
        msg.setText(
            f"Material: {material}\n"
            f"Final Weight: {weight:.2f} kg\n"
            f"Total Payout: \u20b1{payout:.2f}\n\n"
            f"Dispensing coins — please wait..."
        )
        msg.setStyleSheet("QLabel{font-size: 16px;}")
        msg.setStandardButtons(QMessageBox.StandardButton.NoButton)

        # Trigger coin dispensing; close the box when done
        dialog.dispense_coins(payout)

        # Poll until dispensing finishes, then auto-close
        from PyQt6.QtCore import QTimer as _QT
        def _check_done():
            if not getattr(dialog, "_dispense_queue", None):
                msg.accept()
            else:
                _QT.singleShot(300, _check_done)
        _QT.singleShot(300, _check_done)
        msg.exec()

    # ── Admin actions ────────────────────────────────────────────────────────

    def _open_coin_dispenser(self):
        CoinDispenserDialog(self).exec()

    def _trigger_sync(self):
        try:
            import sync_sheets
            sync_sheets.sync_now()
            self.sync_status_label.setText("Sync: triggered — syncing...")
            self.sync_status_label.setStyleSheet(
                self.sync_status_label.styleSheet().replace("color: #555", "color: #FF9800")
                                                   .replace("color: #f44336", "color: #FF9800")
                                                   .replace("color: #4CAF50", "color: #FF9800")
            )
            QTimer.singleShot(3000, self._update_sync_status)
        except Exception as e:
            self.sync_status_label.setText(f"Sync error: {e}")

    def _update_sync_status(self):
        try:
            import sync_sheets
            import database
            status   = sync_sheets.sync_status()
            pending  = status["pending"]
            has_wifi = status["has_wifi"]

            if pending == 0:
                text  = "✓ All records synced to Google Sheets"
                color = "#4CAF50"
            elif has_wifi:
                text  = f"↑ Syncing {pending} pending record(s)..."
                color = "#FF9800"
            else:
                text  = f"⚠ No WiFi — {pending} record(s) pending sync"
                color = "#f44336"

            self.sync_status_label.setText(text)
            self.sync_status_label.setStyleSheet(
                f"font-size: {max(11, int(13*self._scale))}px; "
                f"color: {color}; padding: 4px;"
            )
        except Exception:
            pass

    def _open_data_collection(self):
        DataCollectionDialog(self).exec()

    def _open_hardware_test(self):
        HardwareTestDialog(self).exec()

    def _open_weight_test(self):
        WeightSensorTestDialog(self).exec()