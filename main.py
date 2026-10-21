import os
import time
import subprocess
import threading
import av
import cv2
import pygame
import numpy as np
from djitellopy import Tello

# ================= CONFIGURAÇÕES DE HARDWARE & MONITORES =================
FPS = 10              # Frequência do laço de controle (PID / rc_control)
PANEL_FPS = 5         # Atualização do painel Pygame (telemetria não precisa de mais)
VISION_SCALE = 0.5    # Visão processada em meia resolução (480x360) -> ~4x mais leve
SPEED_VERT = 15       # Subida suave
ALT_MIN_TOF = 30      # Altura mínima em cm
ALT_MAX_TOF = 190     # Altura máxima em cm
CRITICAL_BATTERY = 20 # Bateria mínima (%)

IMG_CENTER_X = 960 // 2
TARGET_SPAN = 600
TELLO_SSID = "TELLO-CFA 143"

# Coordenadas do layout do kanshi (~/.config/kanshi/config). O posicionamento final e a
# tela cheia são garantidos pelas windowRules do labwc (~/.config/labwc/rc.xml), que movem
# cada janela para a saída certa (DSI-1 / HDMI-A-1) pelo título.
# 1. Tela da Raspberry (DSI-1, rotacionada 270°): 480x800 na posição X=2720, Y=271
RASP_POS_X = 2720
RASP_POS_Y = 271
RASP_WIDTH = 480
RASP_HEIGHT = 800

# 2. Monitor Principal (HDMI-A-1): 1920x1080 na posição X=800, Y=0
MONITOR_POS_X = 800
MONITOR_POS_Y = 0
# =========================================================================

# Forçar o Pygame a rodar sobre a camada XWayland com posicionamento absoluto
os.environ['SDL_VIDEODRIVER'] = 'x11'
os.environ['SDL_VIDEO_WINDOW_POS'] = f"{RASP_POS_X},{RASP_POS_Y}"

class RobustPID:
    def __init__(self, kp=0.09, kd=0.035, ki=0.008, output_limits=(-16, 16), integral_limit=8.0):
        self.kp = kp
        self.kd = kd
        self.ki = ki
        self.limits = output_limits
        self.integral_limit = integral_limit
        self.last_error = 0
        self.integral = 0.0
        self.last_time = time.time()

    def compute(self, error):
        now = time.time()
        dt = max(now - self.last_time, 1e-4)

        # Termo Integral com trava anti-windup
        self.integral += error * dt
        self.integral = max(min(self.integral, self.integral_limit), -self.integral_limit)

        derivative = (error - self.last_error) / dt

        output = (self.kp * error) + (self.ki * self.integral) + (self.kd * derivative)
        output = max(min(output, self.limits[1]), self.limits[0])

        self.last_error = error
        self.last_time = now
        return int(output)

    def reset(self):
        self.last_error = 0
        self.integral = 0.0
        self.last_time = time.time()

class LowLatencyFrameReader:
    """Substitui o BackgroundFrameRead do djitellopy: guarda só o quadro mais recente,
    sem buffer no FFmpeg e sem a conversão via PIL (que limitava a ~14 fps e acumulava atraso)."""
    def __init__(self, address):
        self.container = av.open(address, timeout=(Tello.FRAME_GRAB_TIMEOUT, None),
                                 options={'fflags': 'nobuffer', 'flags': 'low_delay'})
        self.stream = self.container.streams.video[0]
        self.stream.thread_type = 'SLICE'  # paraleliza sem adicionar quadros de atraso
        self.lock = threading.Lock()
        self._av_frame = None
        self.frame_id = 0
        self.stopped = False
        self.worker = threading.Thread(target=self._update, daemon=True)
        self.worker.start()

    def _update(self):
        try:
            for av_frame in self.container.decode(self.stream):
                if self.stopped:
                    break
                with self.lock:
                    self._av_frame = av_frame
                    self.frame_id += 1
        except Exception as e:
            print(f"[VIDEO] Leitura interrompida: {e}")
        finally:
            try:
                self.container.close()
            except Exception:
                pass

    def read(self):
        """Retorna (id, frame RGB) do quadro mais recente. A conversão para RGB só é feita
        para o quadro que vai ser exibido, não para todos os decodificados."""
        with self.lock:
            av_frame, frame_id = self._av_frame, self.frame_id
        if av_frame is None:
            return 0, None
        return frame_id, av_frame.to_ndarray(format='rgb24')

    def stop(self):
        self.stopped = True

class TelloStableInspector:
    def __init__(self):
        pygame.init()
        pygame.font.init()
        pygame.display.set_caption("Tello - Painel Vertical")

        # Tela 1: Raspberry Touchscreen (480x800 em X=1920, Y=231)
        self.panel_w = RASP_WIDTH
        self.panel_h = RASP_HEIGHT
        self.screen = pygame.display.set_mode([self.panel_w, self.panel_h], pygame.NOFRAME)

        # Tipografia
        self.font_title = pygame.font.SysFont("Arial", 20, bold=True)
        self.font_huge = pygame.font.SysFont("Arial", 36, bold=True)
        self.font_mid = pygame.font.SysFont("Arial", 17, bold=True)
        self.font_sm = pygame.font.SysFont("Arial", 14)
        self.font_btn = pygame.font.SysFont("Arial", 20, bold=True)

        self.tello = None
        self.frame_read = None
        self.is_connected = False
        self.state = "IDLE"
        self.target_span = TARGET_SPAN

        self.pid_roll = RobustPID(kp=0.09, kd=0.035, ki=0.008, output_limits=(-16, 16))

        # Botões empilhados verticalmente na tela da Rasp
        self.btn_reconnect = pygame.Rect(40, 560, 400, 55)
        self.btn_takeoff = pygame.Rect(40, 630, 400, 65)
        self.btn_land = pygame.Rect(40, 710, 400, 65)

        self.last_telemetry_time = 0
        self.battery = 0
        self.temperature = 0
        self.wifi_status_msg = "Iniciando..."

        # Rastreamento
        self.target_locked = False
        self.building_center_x = IMG_CENTER_X
        self.current_span = TARGET_SPAN
        self.filtered_center_x = float(IMG_CENTER_X)
        self.filtered_span = float(TARGET_SPAN)

        # Tela 2: Janela OpenCV para Câmera no Monitor Principal (HDMI-A-1) em Tela Cheia
        self.cv_window_name = "Tello - Deteccao de Fachada (Camera)"
        # GUI_NORMAL remove a barra de ferramentas/status do Qt que aparecia sobre a imagem
        cv2.namedWindow(self.cv_window_name, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO | cv2.WINDOW_GUI_NORMAL)
        cv2.moveWindow(self.cv_window_name, MONITOR_POS_X, MONITOR_POS_Y)
        cv2.setWindowProperty(self.cv_window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

        pygame.time.set_timer(pygame.USEREVENT + 1, 1000 // FPS)

        # Conectar ao drone na inicialização
        self.connect_drone()

    def ensure_wifi_connection(self):
        """Verifica se está no Wi-Fi do Tello via nmcli; se não estiver, reconecta."""
        try:
            current_wifi = subprocess.check_output(
                ["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"], 
                stderr=subprocess.DEVNULL
            ).decode("utf-8")
            
            for line in current_wifi.splitlines():
                if line.startswith("yes:"):
                    active_ssid = line.split(":")[1].strip()
                    if TELLO_SSID in active_ssid or active_ssid in TELLO_SSID:
                        self.wifi_status_msg = f"Wi-Fi OK: {active_ssid}"
                        return True
            
            self.wifi_status_msg = "Conectando ao Wi-Fi..."
            self.draw_vertical_panel(0, 0, 0)
            pygame.display.flip()

            res = subprocess.run(
                ["nmcli", "dev", "wifi", "connect", TELLO_SSID], 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, 
                text=True, 
                timeout=10
            )
            time.sleep(2)
            if res.returncode == 0:
                self.wifi_status_msg = f"Wi-Fi OK: {TELLO_SSID}"
                return True
            else:
                self.wifi_status_msg = "Falha no Wi-Fi"
                return False
        except Exception as e:
            self.wifi_status_msg = "Erro nmcli / Wi-Fi"
            print(f"[WIFI] Erro: {e}")
            return False

    def connect_drone(self):
        """Reinicia os sockets UDP e reconecta ao Tello após troca de bateria."""
        self.wifi_status_msg = "Checando Wi-Fi..."
        self.draw_vertical_panel(0, 0, 0)
        pygame.display.flip()

        self.ensure_wifi_connection()

        if self.tello is not None:
            try:
                self.tello.streamoff()
                self.tello.end()
            except Exception:
                pass
            self.tello = None

        print("[SISTEMA] Conectando ao SDK Tello...")
        self.wifi_status_msg = "Conectando Tello..."
        try:
            self.tello = Tello()
            self.tello.connect(wait_for_state=False)
            time.sleep(0.5)
            self.tello.streamoff()
            self.tello.streamon()
            # O leitor fica bloqueado na porta UDP 11111 e não pode ser fechado/reaberto;
            # numa reconexão ele é reaproveitado e volta a decodificar quando o vídeo retorna.
            if self.frame_read is None or not self.frame_read.worker.is_alive():
                self.frame_read = LowLatencyFrameReader(self.tello.get_udp_video_address())
            self.is_connected = True
            self.wifi_status_msg = "Drone Pronto!"
            print("[SISTEMA] Drone conectado com sucesso!")
        except Exception as e:
            self.is_connected = False
            self.wifi_status_msg = "Falha conexao Tello"
            print(f"[ERRO] Falha de conexão: {e}")

    def process_vision(self, frame):
        """Deteta pares de varandas azuis no mesmo andar para medir centro e largura (RGB Nativo)."""
        # Segmentação em resolução reduzida; caixas são reescaladas para a imagem original
        inv_scale = 1.0 / VISION_SCALE
        small = cv2.resize(frame, None, fx=VISION_SCALE, fy=VISION_SCALE, interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(small, cv2.COLOR_RGB2HSV)

        lower_blue = np.array([100, 110, 50])
        upper_blue = np.array([135, 255, 255])
        mask_blue = cv2.inRange(hsv, lower_blue, upper_blue)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        mask_blue = cv2.morphologyEx(mask_blue, cv2.MORPH_CLOSE, kernel)

        contours_blue, _ = cv2.findContours(mask_blue, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        valid_boxes = []
        for cnt in contours_blue:
            if cv2.contourArea(cnt) * inv_scale * inv_scale > 300:
                x, y, w, h = (int(v * inv_scale) for v in cv2.boundingRect(cnt))
                if w > h:
                    valid_boxes.append((x, y, w, h, x + w // 2, y + h // 2))
                    cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 100, 255), 2)
                    cv2.putText(frame, "FACHADA", (x, max(20, y - 5)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1)

        cv2.line(frame, (IMG_CENTER_X, 0), (IMG_CENTER_X, 720), (255, 0, 0), 1)

        best_pair = None
        min_y_diff = float("inf")

        if len(valid_boxes) >= 2:
            for i in range(len(valid_boxes)):
                for j in range(i + 1, len(valid_boxes)):
                    b1 = valid_boxes[i]
                    b2 = valid_boxes[j]
                    y_diff = abs(b1[5] - b2[5])
                    x_dist = abs(b1[4] - b2[4])

                    if y_diff < 30 and x_dist > 300:
                        if y_diff < min_y_diff:
                            min_y_diff = y_diff
                            b_left = b1 if b1[4] < b2[4] else b2
                            b_right = b2 if b1[4] < b2[4] else b1
                            best_pair = (b_left, b_right)

        if best_pair is not None:
            b_left, b_right = best_pair

            center_x = (b_left[4] + b_right[4]) // 2
            measured_span = (b_right[0] + b_right[2]) - b_left[0]

            self.filtered_center_x = 0.65 * self.filtered_center_x + 0.35 * center_x
            self.filtered_span = 0.75 * self.filtered_span + 0.25 * measured_span

            self.building_center_x = int(self.filtered_center_x)
            self.current_span = int(self.filtered_span)
            self.target_locked = True

            cv2.line(frame, (b_left[4], b_left[5]), (b_right[4], b_right[5]), (0, 255, 255), 2)
            cv2.circle(frame, (self.building_center_x, (b_left[5] + b_right[5]) // 2), 8, (0, 255, 0), -1)
            cv2.putText(frame, f"Centro: {self.building_center_x}px | Span: {self.current_span}px", 
                        (self.building_center_x - 120, b_left[5] - 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        else:
            self.target_locked = False

        return frame

    def draw_battery_icon_vertical(self, surface, x, y, width=65, height=105):
        terminal_w = width // 2
        terminal_h = 8
        term_x = x + (width - terminal_w) // 2
        pygame.draw.rect(surface, (200, 200, 200), (term_x, y, terminal_w, terminal_h), border_radius=3)

        body_y = y + terminal_h
        body_h = height - terminal_h
        pygame.draw.rect(surface, (230, 230, 230), (x, body_y, width, body_h), 3, border_radius=8)

        pct = max(0.0, min(float(self.battery) / 100.0, 1.0))
        fill_max_h = body_h - 10
        fill_h = int(fill_max_h * pct)
        fill_y = (body_y + body_h - 5) - fill_h

        color = (0, 230, 90) if self.battery > 40 else ((255, 175, 0) if self.battery > CRITICAL_BATTERY else (240, 50, 50))
        if fill_h > 0:
            pygame.draw.rect(surface, color, (x + 5, fill_y, width - 10, fill_h), border_radius=5)

    def draw_thermometer_icon_vertical(self, surface, x, y, width=44, height=105):
        tube_w = width // 2
        tube_x = x + (width - tube_w) // 2
        bulb_radius = width // 2
        bulb_center = (x + width // 2, y + height - bulb_radius)
        tube_h = height - bulb_radius * 2

        pygame.draw.rect(surface, (230, 230, 230), (tube_x, y, tube_w, tube_h), 3, border_radius=6)
        pygame.draw.circle(surface, (230, 230, 230), bulb_center, bulb_radius, 3)

        temp_clamped = max(20.0, min(float(self.temperature), 90.0))
        pct = (temp_clamped - 20.0) / 70.0
        fill_h = int(tube_h * pct)

        col = (0, 200, 255) if self.temperature < 60 else ((255, 160, 0) if self.temperature < 75 else (240, 50, 50))
        pygame.draw.circle(surface, col, bulb_center, bulb_radius - 3)

        if fill_h > 0:
            pygame.draw.rect(surface, col, (tube_x + 3, (y + tube_h) - fill_h, tube_w - 6, fill_h))

    def draw_vertical_panel(self, tof_dist, cmd_roll, cmd_pitch):
        self.screen.fill((18, 22, 28))

        # Cabeçalho
        title_surf = self.font_title.render("CONTROLE & TELEMETRIA", True, (240, 240, 240))
        self.screen.blit(title_surf, (self.panel_w // 2 - title_surf.get_width() // 2, 12))

        # Card Bateria
        card_bat = pygame.Rect(30, 42, 420, 120)
        pygame.draw.rect(self.screen, (28, 34, 44), card_bat, border_radius=12)
        self.draw_battery_icon_vertical(self.screen, 60, 50, width=60, height=100)
        self.screen.blit(self.font_mid.render("NÍVEL DA BATERIA", True, (160, 175, 195)), (155, 68))
        self.screen.blit(self.font_huge.render(f"{self.battery}%", True, (255, 255, 255)), (155, 95))

        # Card Temperatura
        card_temp = pygame.Rect(30, 172, 420, 120)
        pygame.draw.rect(self.screen, (28, 34, 44), card_temp, border_radius=12)
        self.draw_thermometer_icon_vertical(self.screen, 68, 180, width=42, height=100)
        self.screen.blit(self.font_mid.render("TEMPERATURA INTERNA", True, (160, 175, 195)), (155, 198))
        self.screen.blit(self.font_huge.render(f"{self.temperature}°C", True, (255, 255, 255)), (155, 225))

        # Card Telemetria
        card_status = pygame.Rect(30, 302, 420, 245)
        pygame.draw.rect(self.screen, (25, 30, 40), card_status, border_radius=12)

        lock_txt = "BLOQUEADO" if self.target_locked else "A PROCURAR"
        lock_col = (0, 255, 120) if self.target_locked else (255, 140, 0)
        conn_col = (0, 255, 120) if self.is_connected else (255, 50, 50)

        self.screen.blit(self.font_mid.render(f"Rede: {self.wifi_status_msg}", True, conn_col), (45, 312))
        self.screen.blit(self.font_mid.render(f"FSM: {self.state}", True, (255, 215, 0)), (45, 342))
        self.screen.blit(self.font_mid.render(f"Altitude ToF: {tof_dist} cm", True, (0, 220, 255)), (45, 372))
        self.screen.blit(self.font_mid.render("Alvo Fachada: ", True, (200, 200, 200)), (45, 402))
        self.screen.blit(self.font_mid.render(lock_txt, True, lock_col), (165, 402))
        self.screen.blit(self.font_mid.render(f"Largura Atual: {self.current_span} px", True, (220, 220, 220)), (45, 432))
        self.screen.blit(self.font_mid.render(f"Largura Alvo: {self.target_span} px  ([+]/[-])", True, (255, 220, 0)), (45, 462))
        self.screen.blit(self.font_sm.render(f"Roll: {cmd_roll} | Pitch: {cmd_pitch} | V: {SPEED_VERT}", True, (150, 160, 175)), (45, 500))

        # Botão 1: Reconectar Drone / Wi-Fi
        pygame.draw.rect(self.screen, (0, 110, 200), self.btn_reconnect, border_radius=12)
        pygame.draw.rect(self.screen, (255, 255, 255), self.btn_reconnect, 2, border_radius=12)
        lbl_rc = self.font_btn.render("RECONECTAR DRONE / WI-FI", True, (255, 255, 255))
        self.screen.blit(lbl_rc, (self.btn_reconnect.centerx - lbl_rc.get_width() // 2, self.btn_reconnect.centery - lbl_rc.get_height() // 2))

        # Botão 2: Decolar / Iniciar
        takeoff_bg = (0, 170, 70) if self.state == "IDLE" and self.is_connected else (50, 55, 60)
        pygame.draw.rect(self.screen, takeoff_bg, self.btn_takeoff, border_radius=12)
        pygame.draw.rect(self.screen, (255, 255, 255), self.btn_takeoff, 2, border_radius=12)
        lbl_to = self.font_btn.render("DECOLAR / INICIAR", True, (255, 255, 255))
        self.screen.blit(lbl_to, (self.btn_takeoff.centerx - lbl_to.get_width() // 2, self.btn_takeoff.centery - lbl_to.get_height() // 2))

        # Botão 3: Pousar / Parar
        pygame.draw.rect(self.screen, (215, 40, 40), self.btn_land, border_radius=12)
        pygame.draw.rect(self.screen, (255, 255, 255), self.btn_land, 2, border_radius=12)
        lbl_ld = self.font_btn.render("POUSAR / PARAR", True, (255, 255, 255))
        self.screen.blit(lbl_ld, (self.btn_land.centerx - lbl_ld.get_width() // 2, self.btn_land.centery - lbl_ld.get_height() // 2))

    def trigger_takeoff(self):
        if not self.is_connected or self.battery <= CRITICAL_BATTERY:
            print(f"[BLOQUEIO] Conexão ausente ou Bateria crítica ({self.battery}%).")
            return
        if self.state == "IDLE":
            print(f"[CMD] Descolagem iniciada com centro travado e alvo em {self.target_span}px...")
            self.pid_roll.reset()
            self.filtered_center_x = float(IMG_CENTER_X)
            self.filtered_span = float(self.target_span)
            try:
                self.tello.takeoff()
                time.sleep(1)
                self.state = "ASCENDING"
            except Exception as e:
                print(f"[ERRO] Falha ao descolar: {e}")

    def trigger_land(self, reason="Manual"):
        print(f"[CMD] A aterrar ({reason})...")
        self.state = "IDLE"
        if self.tello and self.is_connected:
            self.tello.send_rc_control(0, 0, 0, 0)
            try:
                self.tello.land()
            except Exception:
                pass

    def run(self):
        cmd_roll = 0
        cmd_pitch = 0
        running = True
        last_frame_id = 0
        last_panel_time = 0

        while running:
            current_time = time.time()
            if self.is_connected and (current_time - self.last_telemetry_time > 1.5):
                try:
                    self.battery = self.tello.get_battery()
                    self.temperature = self.tello.get_temperature()

                    if self.battery <= CRITICAL_BATTERY and self.battery > 0 and self.state != "IDLE":
                        print(f"\n[ALERTA] Bateria crítica ({self.battery}%). A aterrar...")
                        self.trigger_land(reason="Bateria Crítica")
                except Exception:
                    pass
                self.last_telemetry_time = current_time

            for event in pygame.event.get():
                if event.type == pygame.USEREVENT + 1:
                    cmd_roll, cmd_pitch = self.control_loop()
                elif event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if self.btn_reconnect.collidepoint(event.pos):
                        self.connect_drone()
                    elif self.btn_takeoff.collidepoint(event.pos):
                        self.trigger_takeoff()
                    elif self.btn_land.collidepoint(event.pos):
                        self.trigger_land(reason="Botão Pousar")
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    elif event.key == pygame.K_SPACE:
                        self.trigger_takeoff()
                    elif event.key == pygame.K_r:
                        self.connect_drone()
                    elif event.key == pygame.K_l:
                        self.trigger_land(reason="Tecla L")
                    elif event.key in (pygame.K_PLUS, pygame.K_KP_PLUS, pygame.K_p):
                        self.target_span += 10
                    elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS, pygame.K_m):
                        self.target_span = max(100, self.target_span - 10)

            # Tela 2: Monitor Externo (OpenCV) - processa cada quadro novo assim que chega
            new_frame = False
            if self.is_connected and self.frame_read is not None:
                frame_id, frame = self.frame_read.read()
                if frame is not None and frame_id != last_frame_id:
                    last_frame_id = frame_id
                    new_frame = True
                    annotated_frame = self.process_vision(frame)
                    bgr_display = cv2.cvtColor(annotated_frame, cv2.COLOR_RGB2BGR)
                    cv2.imshow(self.cv_window_name, bgr_display)
            elif last_frame_id != -1:
                last_frame_id = -1
                blank = np.zeros((720, 960, 3), dtype=np.uint8)
                cv2.putText(blank, "AGUARDANDO CONEXAO COM O DRONE...", (160, 360),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 165, 255), 2)
                cv2.imshow(self.cv_window_name, blank)

            if cv2.waitKey(1) & 0xFF == 27:
                running = False

            # Tela 1: Raspberry Touchscreen (Pygame) - limitada a PANEL_FPS
            if current_time - last_panel_time >= 1 / PANEL_FPS:
                last_panel_time = current_time
                tof_dist = self.tello.get_distance_tof() if (self.is_connected and self.tello) else 0
                self.draw_vertical_panel(tof_dist, cmd_roll, cmd_pitch)
                pygame.display.flip()

            # Sem sleep fixo: só cede a CPU quando ainda não chegou quadro novo
            if not new_frame:
                time.sleep(0.005)

        if self.frame_read is not None:
            self.frame_read.stop()

        if self.tello and self.is_connected:
            self.tello.send_rc_control(0, 0, 0, 0)
            try:
                self.tello.land()
            except Exception:
                pass
            self.tello.streamoff()

        cv2.destroyAllWindows()
        pygame.quit()

    def control_loop(self):
        if self.state == "IDLE" or not self.is_connected or self.tello is None:
            return 0, 0

        tof = self.tello.get_distance_tof()
        if tof <= 0:
            tof = 180

        cmd_vert = 0
        if self.state == "ASCENDING":
            if tof >= ALT_MAX_TOF:
                self.state = "DESCENDING"
                cmd_vert = -SPEED_VERT
            else:
                cmd_vert = SPEED_VERT
        elif self.state == "DESCENDING":
            if tof <= ALT_MIN_TOF:
                self.state = "ASCENDING"
                cmd_vert = SPEED_VERT
            else:
                cmd_vert = -SPEED_VERT

        cmd_roll = 0
        cmd_pitch = 0

        if self.target_locked:
            error_x = self.building_center_x - IMG_CENTER_X
            if abs(error_x) > 6:
                cmd_roll = self.pid_roll.compute(error_x)
            else:
                cmd_roll = 0

            diff_span = self.current_span - self.target_span
            if diff_span > 20:
                cmd_pitch = -7 if diff_span < 50 else -12
            elif diff_span < -20:
                cmd_pitch = 6 if diff_span > -50 else 9
            else:
                cmd_pitch = 0
        else:
            self.pid_roll.reset()

        self.tello.send_rc_control(cmd_roll, cmd_pitch, cmd_vert, 0)
        return cmd_roll, cmd_pitch

if __name__ == "__main__":
    app = TelloStableInspector()
    app.run()
