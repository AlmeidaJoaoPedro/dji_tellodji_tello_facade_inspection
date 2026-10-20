import time
import cv2
import pygame
import numpy as np
from djitellopy import Tello

FPS = 60
SPEED_VERT = 15       # Subida suave
ALT_MIN_TOF = 30      # Altura mínima em cm
ALT_MAX_TOF = 190     # Altura máxima em cm
CRITICAL_BATTERY = 20 # Bateria mínima (%)

IMG_CENTER_X = 960 // 2
TARGET_SPAN = 600     # Largura alvo entre as colunas em píxeis

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

class TelloStableInspector:
    def __init__(self):
        pygame.init()
        pygame.font.init()
        pygame.display.set_caption("Tello - Painel Vertical")

        # Tela 1: Painel em Pé (Vertical: 480 de largura x 800 de altura)
        self.panel_w = 480
        self.panel_h = 800
        self.screen = pygame.display.set_mode([self.panel_w, self.panel_h])

        # Fontes organizadas por tamanho
        self.font_title = pygame.font.SysFont("Arial", 22, bold=True)
        self.font_huge = pygame.font.SysFont("Arial", 38, bold=True)
        self.font_mid = pygame.font.SysFont("Arial", 18, bold=True)
        self.font_sm = pygame.font.SysFont("Arial", 15)
        self.font_btn = pygame.font.SysFont("Arial", 22, bold=True)

        self.tello = Tello()
        self.state = "IDLE"
        self.target_span = TARGET_SPAN

        # PID de Roll
        self.pid_roll = RobustPID(kp=0.09, kd=0.035, ki=0.008, output_limits=(-16, 16))

        # Botões empilhados verticalmente na base da tela
        self.btn_takeoff = pygame.Rect(40, 630, 400, 65)
        self.btn_land = pygame.Rect(40, 710, 400, 65)

        self.last_telemetry_time = 0
        self.battery = 100
        self.temperature = 0

        # Rastreamento
        self.target_locked = False
        self.building_center_x = IMG_CENTER_X
        self.current_span = TARGET_SPAN
        self.filtered_center_x = float(IMG_CENTER_X)
        self.filtered_span = float(TARGET_SPAN)

        # Tela 2: Janela OpenCV para Câmera e Fachada
        self.cv_window_name = "Tello - Deteccao de Fachada (Camera)"
        cv2.namedWindow(self.cv_window_name, cv2.WINDOW_AUTOSIZE)

        pygame.time.set_timer(pygame.USEREVENT + 1, 1000 // FPS)

    def process_vision(self, frame):
        """Deteta pares de varandas azuis no mesmo andar para medir centro e largura (RGB Nativo)."""
        hsv = cv2.cvtColor(frame, cv2.COLOR_RGB2HSV)

        lower_blue = np.array([100, 110, 50])
        upper_blue = np.array([135, 255, 255])
        mask_blue = cv2.inRange(hsv, lower_blue, upper_blue)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        mask_blue = cv2.morphologyEx(mask_blue, cv2.MORPH_CLOSE, kernel)

        contours_blue, _ = cv2.findContours(mask_blue, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        valid_boxes = []
        for cnt in contours_blue:
            if cv2.contourArea(cnt) > 300:
                x, y, w, h = cv2.boundingRect(cnt)
                if w > h:
                    valid_boxes.append((x, y, w, h, x + w // 2, y + h // 2))
                    cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 100, 255), 2)
                    cv2.putText(frame, "FACHADA", (x, max(20, y - 5)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1)

        # Linha central azul (referência da câmara do drone)
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

            # Filtro com menor atraso temporal (65% histórico / 35% leitura atual)
            self.filtered_center_x = 0.65 * self.filtered_center_x + 0.35 * center_x
            self.filtered_span = 0.75 * self.filtered_span + 0.25 * measured_span

            self.building_center_x = int(self.filtered_center_x)
            self.current_span = int(self.filtered_span)
            self.target_locked = True

            # Marcadores visuais
            cv2.line(frame, (b_left[4], b_left[5]), (b_right[4], b_right[5]), (0, 255, 255), 2)
            cv2.circle(frame, (self.building_center_x, (b_left[5] + b_right[5]) // 2), 8, (0, 255, 0), -1)
            cv2.putText(frame, f"Centro: {self.building_center_x}px | Span: {self.current_span}px", 
                        (self.building_center_x - 120, b_left[5] - 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        else:
            self.target_locked = False

        return frame

    def draw_battery_icon_vertical(self, surface, x, y, width=70, height=120):
        """Renderiza um ícone de bateria vertical grande com nível proporcional."""
        terminal_w = width // 2
        terminal_h = 10
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

    def draw_thermometer_icon_vertical(self, surface, x, y, width=46, height=120):
        """Renderiza um termômetro vertical grande com bulbo na base."""
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

        # 1. Título do Painel
        title_surf = self.font_title.render("CONTROLE & TELEMETRIA", True, (240, 240, 240))
        self.screen.blit(title_surf, (self.panel_w // 2 - title_surf.get_width() // 2, 20))

        # 2. Card de Bateria Vertical (Grande)
        card_bat = pygame.Rect(30, 60, 420, 145)
        pygame.draw.rect(self.screen, (28, 34, 44), card_bat, border_radius=12)
        self.draw_battery_icon_vertical(self.screen, 60, 72, width=65, height=120)
        self.screen.blit(self.font_mid.render("NÍVEL DA BATERIA", True, (160, 175, 195)), (155, 95))
        self.screen.blit(self.font_huge.render(f"{self.battery}%", True, (255, 255, 255)), (155, 125))

        # 3. Card de Temperatura Vertical (Grande)
        card_temp = pygame.Rect(30, 220, 420, 145)
        pygame.draw.rect(self.screen, (28, 34, 44), card_temp, border_radius=12)
        self.draw_thermometer_icon_vertical(self.screen, 70, 232, width=46, height=120)
        self.screen.blit(self.font_mid.render("TEMPERATURA INTERNA", True, (160, 175, 195)), (155, 255))
        self.screen.blit(self.font_huge.render(f"{self.temperature}°C", True, (255, 255, 255)), (155, 285))

        # 4. Status de Voo, ToF e Alvo
        card_status = pygame.Rect(30, 380, 420, 225)
        pygame.draw.rect(self.screen, (25, 30, 40), card_status, border_radius=12)

        lock_txt = "BLOQUEADO" if self.target_locked else "A PROCURAR"
        lock_col = (0, 255, 120) if self.target_locked else (255, 140, 0)

        self.screen.blit(self.font_mid.render(f"FSM: {self.state}", True, (255, 215, 0)), (50, 395))
        self.screen.blit(self.font_mid.render(f"Altitude ToF: {tof_dist} cm", True, (0, 220, 255)), (50, 430))
        self.screen.blit(self.font_mid.render("Alvo Fachada: ", True, (200, 200, 200)), (50, 465))
        self.screen.blit(self.font_mid.render(lock_txt, True, lock_col), (180, 465))
        self.screen.blit(self.font_mid.render(f"Largura Atual: {self.current_span} px", True, (220, 220, 220)), (50, 500))
        self.screen.blit(self.font_mid.render(f"Largura Alvo: {self.target_span} px  ([+]/[-])", True, (255, 220, 0)), (50, 535))
        self.screen.blit(self.font_sm.render(f"Comandos Ativos: Roll = {cmd_roll} | Pitch = {cmd_pitch}", True, (150, 160, 175)), (50, 575))

        # 5. Botão Decolar / Iniciar
        takeoff_bg = (0, 170, 70) if self.state == "IDLE" else (50, 55, 60)
        pygame.draw.rect(self.screen, takeoff_bg, self.btn_takeoff, border_radius=12)
        pygame.draw.rect(self.screen, (255, 255, 255), self.btn_takeoff, 2, border_radius=12)
        lbl_to = self.font_btn.render("DECOLAR / INICIAR", True, (255, 255, 255))
        self.screen.blit(lbl_to, (self.btn_takeoff.centerx - lbl_to.get_width() // 2, self.btn_takeoff.centery - lbl_to.get_height() // 2))

        # 6. Botão Pousar / Parar
        pygame.draw.rect(self.screen, (215, 40, 40), self.btn_land, border_radius=12)
        pygame.draw.rect(self.screen, (255, 255, 255), self.btn_land, 2, border_radius=12)
        lbl_ld = self.font_btn.render("POUSAR / PARAR", True, (255, 255, 255))
        self.screen.blit(lbl_ld, (self.btn_land.centerx - lbl_ld.get_width() // 2, self.btn_land.centery - lbl_ld.get_height() // 2))

    def trigger_takeoff(self):
        if self.battery <= CRITICAL_BATTERY:
            print(f"[BLOQUEIO] Bateria crítica ({self.battery}%).")
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
        self.tello.send_rc_control(0, 0, 0, 0)
        try:
            self.tello.land()
        except Exception:
            pass

    def run(self):
        self.tello.connect(wait_for_state=False)
        self.tello.streamoff()
        self.tello.streamon()
        frame_read = self.tello.get_frame_read()

        cmd_roll = 0
        cmd_pitch = 0
        running = True

        while running:
            current_time = time.time()
            if current_time - self.last_telemetry_time > 1.5:
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
                    if self.btn_takeoff.collidepoint(event.pos):
                        self.trigger_takeoff()
                    elif self.btn_land.collidepoint(event.pos):
                        self.trigger_land(reason="Botão Pousar")
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    elif event.key == pygame.K_SPACE:
                        self.trigger_takeoff()
                    elif event.key == pygame.K_l:
                        self.trigger_land(reason="Tecla L")
                    elif event.key in (pygame.K_PLUS, pygame.K_KP_PLUS, pygame.K_p):
                        self.target_span += 10
                    elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS, pygame.K_m):
                        self.target_span = max(100, self.target_span - 10)

            # Tela 2: Exibição da Câmera no OpenCV (Convertido RGB -> BGR para preservar as cores reais)
            frame = frame_read.frame
            if frame is not None:
                annotated_frame = self.process_vision(frame.copy())
                bgr_display = cv2.cvtColor(annotated_frame, cv2.COLOR_RGB2BGR)
                cv2.imshow(self.cv_window_name, bgr_display)
                if cv2.waitKey(1) & 0xFF == 27:
                    running = False

            # Tela 1: Renderização do Painel Vertical em Pygame (480 x 800)
            tof_dist = self.tello.get_distance_tof()
            self.draw_vertical_panel(tof_dist, cmd_roll, cmd_pitch)
            pygame.display.flip()

            time.sleep(1 / FPS)

        self.tello.send_rc_control(0, 0, 0, 0)
        try:
            self.tello.land()
        except Exception:
            pass
        self.tello.streamoff()
        cv2.destroyAllWindows()
        pygame.quit()

    def control_loop(self):
        if self.state == "IDLE":
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
