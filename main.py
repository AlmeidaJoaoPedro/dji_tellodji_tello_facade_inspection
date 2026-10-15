import time
import cv2
import pygame
import numpy as np
from djitellopy import Tello

FPS = 60
SPEED_VERT = 30       # Subida suave
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
        pygame.display.set_caption("Tello - Inspecao Estavel de Fachada (Centro Cravado)")
        self.width = 960
        self.height = 720
        self.screen = pygame.display.set_mode([self.width, self.height])
        self.font = pygame.font.SysFont("Arial", 16, bold=True)
        self.font_btn = pygame.font.SysFont("Arial", 18, bold=True)
        self.font_calib = pygame.font.SysFont("Arial", 20, bold=True)

        self.tello = Tello()
        self.state = "IDLE"

        self.target_span = TARGET_SPAN

        # PID de Roll com ganhos otimizados para cravar o centro
        self.pid_roll = RobustPID(kp=0.09, kd=0.035, ki=0.008, output_limits=(-16, 16))

        # Botões
        self.btn_takeoff = pygame.Rect(30, 640, 200, 45)
        self.btn_land = pygame.Rect(250, 640, 200, 45)

        self.last_telemetry_time = 0
        self.battery = 100
        self.temperature = 0

        # Rastreamento
        self.target_locked = False
        self.building_center_x = IMG_CENTER_X
        self.current_span = TARGET_SPAN
        self.filtered_center_x = float(IMG_CENTER_X)
        self.filtered_span = float(TARGET_SPAN)

        pygame.time.set_timer(pygame.USEREVENT + 1, 1000 // FPS)

    def process_vision(self, frame):
        """Deteta pares de varandas azuis no mesmo andar para medir centro e largura."""
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
        cv2.line(frame, (IMG_CENTER_X, 0), (IMG_CENTER_X, self.height), (255, 0, 0), 1)

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

    def draw_hud(self, tof_dist, cmd_roll, cmd_pitch):
        overlay = pygame.Surface((self.width, 50), pygame.SRCALPHA)
        overlay.fill((20, 20, 20, 200))
        self.screen.blit(overlay, (0, 0))

        # Bateria
        bat_color = (0, 230, 0) if self.battery > 40 else ((255, 180, 0) if self.battery > CRITICAL_BATTERY else (255, 50, 50))
        pygame.draw.rect(self.screen, (200, 200, 200), (20, 15, 36, 18), 2, border_radius=3)
        pygame.draw.rect(self.screen, (200, 200, 200), (56, 19, 3, 10))
        fill_w = max(0, int((min(self.battery, 100) / 100.0) * 32))
        pygame.draw.rect(self.screen, bat_color, (22, 17, fill_w, 14), border_radius=2)
        self.screen.blit(self.font.render(f"{self.battery}%", True, (240, 240, 240)), (68, 15))

        # Altitude
        self.screen.blit(self.font.render(f"Alt: {tof_dist} cm", True, (0, 220, 255)), (145, 15))

        # Telemetria do Alvo
        lock_txt = "BLOQUEADO" if self.target_locked else "A PROCURAR"
        lock_col = (0, 255, 0) if self.target_locked else (255, 120, 0)
        self.screen.blit(self.font.render(f"Alvo: {lock_txt}", True, lock_col), (270, 15))
        self.screen.blit(self.font.render(f"R:{cmd_roll} | P:{cmd_pitch}", True, (255, 215, 0)), (450, 15))
        self.screen.blit(self.font.render(f"FSM: {self.state}", True, (200, 200, 200)), (680, 15))

        if self.state == "IDLE":
            banner = pygame.Surface((self.width - 60, 55), pygame.SRCALPHA)
            banner.fill((10, 10, 10, 215))
            self.screen.blit(banner, (30, 60))
            pygame.draw.rect(self.screen, (255, 215, 0), (30, 60, self.width - 60, 55), 2, border_radius=5)

            calib_msg = f"DISTANCIA:  Atual: {self.current_span} px   |   Alvo: {self.target_span} px"
            self.screen.blit(self.font_calib.render(calib_msg, True, (255, 255, 0)), (45, 68))
            self.screen.blit(self.font.render("Use [+] e [-] para alterar o Alvo se necessario.", True, (200, 200, 200)), (45, 93))

        # Botões
        takeoff_color = (0, 170, 70) if self.state == "IDLE" else (60, 60, 60)
        pygame.draw.rect(self.screen, takeoff_color, self.btn_takeoff, border_radius=8)
        pygame.draw.rect(self.screen, (255, 255, 255), self.btn_takeoff, 2, border_radius=8)
        self.screen.blit(self.font_btn.render("DECOLAR / INICIAR", True, (255, 255, 255)), (self.btn_takeoff.x + 14, self.btn_takeoff.y + 12))

        pygame.draw.rect(self.screen, (210, 40, 40), self.btn_land, border_radius=8)
        pygame.draw.rect(self.screen, (255, 255, 255), self.btn_land, 2, border_radius=8)
        self.screen.blit(self.font_btn.render("POUSAR / PARAR", True, (255, 255, 255)), (self.btn_land.x + 22, self.btn_land.y + 12))

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

            frame = frame_read.frame
            if frame is not None:
                annotated_frame = self.process_vision(frame.copy())
                display_frame = np.rot90(annotated_frame)
                display_frame = np.flipud(display_frame)
                self.screen.blit(pygame.surfarray.make_surface(display_frame), (0, 0))

                tof_dist = self.tello.get_distance_tof()
                self.draw_hud(tof_dist, cmd_roll, cmd_pitch)

            pygame.display.update()
            time.sleep(1 / FPS)

        self.tello.send_rc_control(0, 0, 0, 0)
        try:
            self.tello.land()
        except Exception:
            pass
        self.tello.streamoff()
        pygame.quit()

    def control_loop(self):
        if self.state == "IDLE":
            return 0, 0

        tof = self.tello.get_distance_tof()
        if tof <= 0:
            tof = 180

        # Subida / Descida via sensor ToF
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
            # 1. ROLL (Lateral):
            # Deadband reduzida para 6 px para cravar no centro geométrico
            error_x = self.building_center_x - IMG_CENTER_X
            if abs(error_x) > 6:
                cmd_roll = self.pid_roll.compute(error_x)
            else:
                cmd_roll = 0

            # 2. PITCH (Distância frontal rigorosa):
            diff_span = self.current_span - self.target_span
            if diff_span > 20:
                # Muito perto -> recua
                cmd_pitch = -7 if diff_span < 50 else -12
            elif diff_span < -20:
                # Muito longe -> avança
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
