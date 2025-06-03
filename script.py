#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import glob 
import subprocess

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout,
    QPushButton, QLabel, QLineEdit, QFileDialog, QTextEdit, QMessageBox,
    QSizePolicy, QComboBox, QGroupBox, QProgressBar
)
from PyQt6.QtCore import Qt, QThread, QObject, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QIntValidator

# --- Configurações Padrão ---
DEFAULT_FFMPEG_CONFIG = {
    "VIDEO_CODEC_AMF": "h264_amf",
    "RC_MODE": "cqp",
    "QP_VALUE": "23",
    "BITRATE_VBR": "5M",
    "MAX_BITRATE_VBR": "8M",
    "QUALITY_PRESET": "quality",
    "AUDIO_CODEC": "aac",
    "AUDIO_BITRATE": "192k",
}
DEFAULT_INPUT_FORMATS = "mp4,mkv,avi,mov,flv,wmv,webm" # Formatos de entrada padrão

class ConversionWorker(QObject):
    progress_update = pyqtSignal(str)
    overall_progress = pyqtSignal(int, int)
    conversion_finished = pyqtSignal(str)
    error_critical = pyqtSignal(str)

    def __init__(self, input_dir, output_dir, ffmpeg_params, target_extensions_str_list):
        super().__init__()
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.ffmpeg_params = ffmpeg_params
        self.target_extensions = [ext.lower() for ext in target_extensions_str_list if ext] # Normaliza para minúsculas
        self._is_running = False
        self.current_process = None

    @pyqtSlot()
    def run_conversions(self):
        self._is_running = True
        cfg = self.ffmpeg_params

        try:
            os.makedirs(self.output_dir, exist_ok=True)
        except OSError as e:
            self.error_critical.emit(f"Erro crítico ao criar diretório de saída '{self.output_dir}': {e}")
            return

        files_to_convert = []
        if not self.target_extensions:
            self.progress_update.emit("Nenhum formato de entrada especificado.")
            self.conversion_finished.emit("Nenhum formato de entrada para procurar.")
            return
            
        self.progress_update.emit(f"Procurando por arquivos com extensões: {', '.join(self.target_extensions)} em '{self.input_dir}'")
        
        try:
            all_files_in_dir = os.listdir(self.input_dir)
            for filename in all_files_in_dir:
                # Verifica a extensão de forma case-insensitive
                file_ext_lower = filename.split('.')[-1].lower() if '.' in filename else ""
                if file_ext_lower in self.target_extensions:
                    full_path = os.path.join(self.input_dir, filename)
                    if os.path.isfile(full_path):
                         files_to_convert.append(full_path)
        except FileNotFoundError:
            self.error_critical.emit(f"Erro: Diretório de entrada não encontrado: {self.input_dir}")
            return
        except Exception as e:
            self.error_critical.emit(f"Erro ao listar arquivos no diretório de entrada: {e}")
            return


        files_to_convert = sorted(list(set(files_to_convert))) # Ordena e remove duplicatas

        if not files_to_convert:
            self.progress_update.emit(f"Nenhum arquivo com os formatos especificados ({', '.join(self.target_extensions)}) encontrado em '{self.input_dir}'.")
            self.conversion_finished.emit("Nenhum arquivo para converter.")
            return

        self.progress_update.emit(f"Encontrados {len(files_to_convert)} arquivo(s) para processar.")
        
        total_files = len(files_to_convert)
        files_processed_count = 0
        files_succeeded_count = 0
        self.overall_progress.emit(0, total_files)

        for i, file_path in enumerate(files_to_convert):
            if not self._is_running:
                self.progress_update.emit("Conversão cancelada pelo usuário.")
                break
            
            files_processed_count +=1
            filename_with_ext = os.path.basename(file_path)
            filename_no_ext, _ = os.path.splitext(filename_with_ext)
            
            video_codec_name_for_file = cfg['VIDEO_CODEC_AMF'].replace('_amf', '').replace('h', 'x')
            output_filename = f"{filename_no_ext}_jellyfin_{video_codec_name_for_file}_gpu.mp4" # Saída sempre .mp4
            output_file_path = os.path.join(self.output_dir, output_filename)

            self.progress_update.emit(f"[{i+1}/{total_files}] Convertendo: {filename_with_ext}...")

            ffmpeg_cmd_list = ["ffmpeg", "-i", file_path]

            if cfg["RC_MODE"] == "cqp":
                ffmpeg_cmd_list.extend(["-c:v", cfg["VIDEO_CODEC_AMF"], "-rc", cfg["RC_MODE"], 
                                        "-qp", cfg["QP_VALUE"], "-quality", cfg["QUALITY_PRESET"]])
            elif cfg["RC_MODE"] == "vbr_peak":
                ffmpeg_cmd_list.extend(["-c:v", cfg["VIDEO_CODEC_AMF"], "-rc", cfg["RC_MODE"], 
                                        "-b:v", cfg["BITRATE_VBR"], "-maxrate", cfg["MAX_BITRATE_VBR"], 
                                        "-quality", cfg["QUALITY_PRESET"]])
            else: 
                self.progress_update.emit(f"Modo RC '{cfg['RC_MODE']}' desconhecido/inválido. Usando CQP (QP 23), quality 'quality'.")
                ffmpeg_cmd_list.extend(["-c:v", cfg["VIDEO_CODEC_AMF"], "-rc", "cqp", 
                                        "-qp", "23", "-quality", "quality"])
            
            ffmpeg_cmd_list.extend(["-c:a", cfg["AUDIO_CODEC"], "-b:a", cfg["AUDIO_BITRATE"], 
                                    "-movflags", "+faststart", "-y", output_file_path])

            try:
                self.current_process = subprocess.Popen(ffmpeg_cmd_list, 
                                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                                                        text=True, encoding='utf-8', errors='replace',
                                                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                stdout, stderr = self.current_process.communicate()
                return_code = self.current_process.returncode
                self.current_process = None

                if not self._is_running and return_code !=0 :
                    self.progress_update.emit(f"Conversão de {filename_with_ext} interrompida.")
                elif return_code == 0:
                    self.progress_update.emit(f"Sucesso: {output_filename}")
                    files_succeeded_count += 1
                else:
                    self.progress_update.emit(f"Erro ao converter {filename_with_ext} (Status: {return_code}).")
                    if stdout: self.progress_update.emit(f"FFmpeg stdout (pode ser longo):\n{stdout[:1000]}...") # Limita a saída
                    if stderr: self.progress_update.emit(f"FFmpeg stderr (pode ser longo):\n{stderr[:1000]}...") # Limita a saída

            except FileNotFoundError:
                self.error_critical.emit("Erro Crítico: 'ffmpeg' não encontrado. Verifique a instalação e o PATH.")
                self._is_running = False
                return 
            except Exception as e:
                self.progress_update.emit(f"Exceção durante conversão de {filename_with_ext}: {e}")
                if self.current_process:
                    self.current_process.kill()
                    self.current_process = None
            
            self.overall_progress.emit(i + 1, total_files)
        
        if self._is_running:
            summary = f"Conversão concluída. {files_succeeded_count}/{total_files} arquivos convertidos com sucesso."
        else:
            summary = f"Conversão cancelada. {files_succeeded_count}/{files_processed_count} arquivos processados antes do cancelamento."
        self.conversion_finished.emit(summary)

    @pyqtSlot()
    def stop_conversions(self):
        self.progress_update.emit("Sinal de cancelamento recebido...")
        self._is_running = False
        if self.current_process:
            self.progress_update.emit("Tentando interromper o processo FFmpeg atual...")
            try:
                self.current_process.terminate() 
                self.current_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.progress_update.emit("FFmpeg não terminou, forçando interrupção (kill)...")
                self.current_process.kill()
            except Exception as e:
                self.progress_update.emit(f"Erro ao tentar parar o processo: {e}")
            self.current_process = None


class ConverterApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.input_dir_path = ""
        self.output_dir_path = ""
        self.conversion_thread = None
        self.conversion_worker = None
        self.initUI()

    def initUI(self):
        self.setWindowTitle('Conversor de Vídeo Universal (FFmpeg AMD AMF)')
        self.setGeometry(100, 100, 800, 750) # Aumentar altura para novo campo

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # --- Seleção de Pastas e Formatos ---
        folder_selection_group = QGroupBox("Seleção de Arquivos")
        folder_selection_layout = QGridLayout() # Usar GridLayout para alinhar melhor

        self.input_label = QLabel("Pasta de Entrada:")
        self.input_lineedit = QLineEdit()
        self.input_lineedit.setReadOnly(True)
        self.input_button = QPushButton("Selecionar...")
        self.input_button.clicked.connect(self.select_input_folder)
        folder_selection_layout.addWidget(self.input_label, 0, 0)
        folder_selection_layout.addWidget(self.input_lineedit, 0, 1, 1, 2) # Ocupa 2 colunas
        folder_selection_layout.addWidget(self.input_button, 0, 3)

        self.output_label = QLabel("Pasta de Saída: ")
        self.output_lineedit = QLineEdit()
        self.output_lineedit.setReadOnly(True)
        self.output_button = QPushButton("Selecionar...")
        self.output_button.clicked.connect(self.select_output_folder)
        folder_selection_layout.addWidget(self.output_label, 1, 0)
        folder_selection_layout.addWidget(self.output_lineedit, 1, 1, 1, 2)
        folder_selection_layout.addWidget(self.output_button, 1, 3)

        self.input_formats_label = QLabel("Formatos de Entrada (ex: mp4,mkv):")
        self.input_formats_edit = QLineEdit(DEFAULT_INPUT_FORMATS)
        folder_selection_layout.addWidget(self.input_formats_label, 2, 0)
        folder_selection_layout.addWidget(self.input_formats_edit, 2, 1, 1, 3) # Ocupa 3 colunas
        
        folder_selection_group.setLayout(folder_selection_layout)
        main_layout.addWidget(folder_selection_group)


        # --- Configurações do FFmpeg ---
        settings_groupbox = QGroupBox("Configurações do FFmpeg")
        settings_form_layout = QFormLayout()

        self.video_codec_combo = QComboBox()
        self.video_codec_combo.addItems([DEFAULT_FFMPEG_CONFIG["VIDEO_CODEC_AMF"], "hevc_amf"])
        settings_form_layout.addRow("Codec de Vídeo (GPU):", self.video_codec_combo)

        self.rc_mode_combo = QComboBox()
        self.rc_mode_combo.addItems([DEFAULT_FFMPEG_CONFIG["RC_MODE"], "vbr_peak"]) # Adicionar "cbr" se quiser
        self.rc_mode_combo.currentTextChanged.connect(self.update_ffmpeg_options_visibility)
        settings_form_layout.addRow("Modo de Controle de Taxa (RC):", self.rc_mode_combo)

        self.qp_label = QLabel("Valor QP (0-51):")
        self.qp_value_edit = QLineEdit(DEFAULT_FFMPEG_CONFIG["QP_VALUE"])
        self.qp_value_edit.setValidator(QIntValidator(0, 51, self))
        settings_form_layout.addRow(self.qp_label, self.qp_value_edit)

        self.bitrate_label = QLabel("Bitrate (ex: 5M):")
        self.bitrate_edit = QLineEdit(DEFAULT_FFMPEG_CONFIG["BITRATE_VBR"])
        settings_form_layout.addRow(self.bitrate_label, self.bitrate_edit)
        
        self.max_bitrate_label = QLabel("Max Bitrate (ex: 8M):")
        self.max_bitrate_edit = QLineEdit(DEFAULT_FFMPEG_CONFIG["MAX_BITRATE_VBR"])
        settings_form_layout.addRow(self.max_bitrate_label, self.max_bitrate_edit)

        self.quality_preset_combo = QComboBox()
        self.quality_preset_combo.addItems([DEFAULT_FFMPEG_CONFIG["QUALITY_PRESET"], "balanced", "speed"])
        settings_form_layout.addRow("Preset de Qualidade:", self.quality_preset_combo)

        self.audio_codec_combo = QComboBox()
        self.audio_codec_combo.addItems([DEFAULT_FFMPEG_CONFIG["AUDIO_CODEC"], "ac3", "copy"])
        settings_form_layout.addRow("Codec de Áudio:", self.audio_codec_combo)

        self.audio_bitrate_edit = QLineEdit(DEFAULT_FFMPEG_CONFIG["AUDIO_BITRATE"])
        settings_form_layout.addRow("Bitrate de Áudio (ex: 192k):", self.audio_bitrate_edit)
        
        settings_groupbox.setLayout(settings_form_layout)
        main_layout.addWidget(settings_groupbox)
        self.update_ffmpeg_options_visibility()

        # --- Botões de Ação---
        action_layout = QHBoxLayout()
        self.start_button = QPushButton("Iniciar Conversão")
        self.start_button.clicked.connect(self.start_conversion_process)
        self.start_button.setFixedHeight(40)
        self.cancel_button = QPushButton("Cancelar Conversão")
        self.cancel_button.clicked.connect(self.cancel_conversion_process)
        self.cancel_button.setFixedHeight(40)
        self.cancel_button.setEnabled(False)
        action_layout.addWidget(self.start_button)
        action_layout.addWidget(self.cancel_button)
        main_layout.addLayout(action_layout)

        # --- Barra de Progresso ---
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%v/%m (%p%)")
        main_layout.addWidget(QLabel("Progresso Geral:"))
        main_layout.addWidget(self.progress_bar)

        # --- Log ---
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        log_label_layout = QHBoxLayout()
        log_label_layout.addWidget(QLabel("Log da Conversão:"))
        log_label_layout.addStretch()
        self.clear_log_button = QPushButton("Limpar Log")
        self.clear_log_button.clicked.connect(self.log_area.clear)
        log_label_layout.addWidget(self.clear_log_button)
        main_layout.addLayout(log_label_layout)
        main_layout.addWidget(self.log_area)

    @pyqtSlot()
    def update_ffmpeg_options_visibility(self): 
        rc_mode = self.rc_mode_combo.currentText()
        is_cqp = (rc_mode == "cqp")
        is_vbr_cbr = (rc_mode == "vbr_peak" or rc_mode == "cbr")

        self.qp_label.setVisible(is_cqp)
        self.qp_value_edit.setVisible(is_cqp)

        self.bitrate_label.setVisible(is_vbr_cbr)
        self.bitrate_edit.setVisible(is_vbr_cbr)
        self.max_bitrate_label.setVisible(is_vbr_cbr) 
        self.max_bitrate_edit.setVisible(is_vbr_cbr)


    def select_input_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Selecionar Pasta de Entrada", self.input_dir_path or os.path.expanduser("~"))
        if folder:
            self.input_dir_path = folder
            self.input_lineedit.setText(folder)
            self.append_log_message(f"Pasta de entrada selecionada: {folder}")
            if not self.output_dir_path or self.output_dir_path == os.path.join(os.path.dirname(self.input_dir_path), "convertidos_pyqt_universal"):
                suggested_output = os.path.join(folder, "convertidos_pyqt_universal") # Nome de pasta diferente
                self.output_dir_path = suggested_output
                self.output_lineedit.setText(suggested_output)

    def select_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Selecionar Pasta de Saída", self.output_dir_path or os.path.expanduser("~"))
        if folder:
            self.output_dir_path = folder
            self.output_lineedit.setText(folder)
            self.append_log_message(f"Pasta de saída selecionada: {folder}")

    def start_conversion_process(self):
        if not self.input_dir_path:
            QMessageBox.warning(self, "Aviso", "Por favor, selecione uma pasta de entrada.")
            return
        if not self.output_dir_path:
            if self.input_dir_path:
                 self.output_dir_path = os.path.join(self.input_dir_path, "convertidos_pyqt_universal")
                 self.output_lineedit.setText(self.output_dir_path)
            else:
                QMessageBox.warning(self, "Aviso", "Por favor, selecione uma pasta de saída.")
                return
        
        input_formats_str = self.input_formats_edit.text()
        target_extensions = [ext.strip().lstrip('.') for ext in input_formats_str.split(',') if ext.strip()]
        if not target_extensions:
            QMessageBox.warning(self, "Aviso", "Por favor, especifique pelo menos um formato de arquivo de entrada.")
            return

        current_ffmpeg_params = { 
            "VIDEO_CODEC_AMF": self.video_codec_combo.currentText(),
            "RC_MODE": self.rc_mode_combo.currentText(),
            "QP_VALUE": self.qp_value_edit.text(),
            "BITRATE_VBR": self.bitrate_edit.text(),
            "MAX_BITRATE_VBR": self.max_bitrate_edit.text(),
            "QUALITY_PRESET": self.quality_preset_combo.currentText(),
            "AUDIO_CODEC": self.audio_codec_combo.currentText(),
            "AUDIO_BITRATE": self.audio_bitrate_edit.text(),
        }

        self.append_log_message(f"Iniciando processo de conversão para formatos: {', '.join(target_extensions)}")
        self.append_log_message("Com as seguintes configurações FFmpeg:")
        for key, value in current_ffmpeg_params.items():
            self.append_log_message(f"  {key}: {value}")
        
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(0) # Será definido pelo worker

        self.conversion_thread = QThread()
        # Passa target_extensions para o worker
        self.conversion_worker = ConversionWorker(self.input_dir_path, self.output_dir_path, current_ffmpeg_params, target_extensions)
        self.conversion_worker.moveToThread(self.conversion_thread)

        self.conversion_worker.progress_update.connect(self.append_log_message)
        self.conversion_worker.overall_progress.connect(self.update_overall_progress_bar)
        self.conversion_worker.conversion_finished.connect(self.handle_conversion_finished)
        self.conversion_worker.error_critical.connect(self.handle_critical_error)

        self.conversion_thread.started.connect(self.conversion_worker.run_conversions)
        self.conversion_thread.finished.connect(self.conversion_worker.deleteLater)
        self.conversion_thread.finished.connect(self.conversion_thread.deleteLater)
        
        self.conversion_thread.start()

    def cancel_conversion_process(self): 
        self.append_log_message("Tentando cancelar a conversão...")
        if self.conversion_worker:
            self.conversion_worker.stop_conversions()

    @pyqtSlot(str)
    def append_log_message(self, message): 
        self.log_area.append(message)
        self.log_area.verticalScrollBar().setValue(self.log_area.verticalScrollBar().maximum())

    @pyqtSlot(int, int)
    def update_overall_progress_bar(self, current_value, max_value):
        if self.progress_bar.maximum() != max_value: # Define o máximo apenas uma vez ou se mudar
            self.progress_bar.setMaximum(max_value)
        self.progress_bar.setValue(current_value)

    @pyqtSlot(str)
    def handle_conversion_finished(self, summary_message): # Modificado para lidar com barra de progresso
        self.append_log_message(summary_message)
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        # Se a conversão foi concluída (não cancelada) e houve arquivos, garante que a barra chegue a 100% do valor máximo
        if self.conversion_worker and self.conversion_worker._is_running and self.progress_bar.maximum() > 0 :
             self.progress_bar.setValue(self.progress_bar.maximum())
        elif self.progress_bar.maximum() == 0 and "Nenhum arquivo para converter." not in summary_message : # Caso não haja arquivos, o máximo pode ser 0
             pass # Não faz nada com a barra se não houve arquivos

        if self.conversion_thread and self.conversion_thread.isRunning():
             self.conversion_thread.quit()
             self.conversion_thread.wait()
        self.conversion_thread = None
        self.conversion_worker = None

    @pyqtSlot(str)
    def handle_critical_error(self, error_message): 
        QMessageBox.critical(self, "Erro Crítico", error_message)
        self.append_log_message(f"ERRO CRÍTICO: {error_message}")
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        if self.conversion_thread and self.conversion_thread.isRunning():
             self.conversion_thread.quit()
             self.conversion_thread.wait()
        self.conversion_thread = None
        self.conversion_worker = None
        
    def closeEvent(self, event): 
        if self.conversion_thread and self.conversion_thread.isRunning():
            reply = QMessageBox.question(self, 'Sair', 
                                       "Uma conversão está em progresso. Deseja realmente sair e cancelar?",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
                                       QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.append_log_message("Fechando aplicação, tentando parar conversão...")
                if self.conversion_worker:
                    self.conversion_worker.stop_conversions()
                self.conversion_thread.quit()
                if not self.conversion_thread.wait(3000):
                    self.append_log_message("Thread de conversão não encerrou a tempo.")
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = ConverterApp()
    ex.show()
    sys.exit(app.exec())
