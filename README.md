# 🚁 DJI Tello Autonomous Façade Inspection

Sistema de inspeção vertical autônoma e rastreamento visual de fachadas prediais com o drone DJI Tello, rodando em um **Raspberry Pi 4** com **tela touch oficial de 7"** (central de controle) e **monitor HDMI** (imagem da câmera).

O drone identifica pares de elementos azuis na fachada (maquete), mantém o centro da fachada alinhado com a câmera usando um controlador PID, ajusta a distância frontal pela largura aparente do alvo e sobe/desce automaticamente usando o sensor de distância ToF.

---

## 📑 Sumário

1. [Hardware necessário](#-hardware-necessário)
2. [Como o sistema é organizado](#-como-o-sistema-é-organizado)
3. [Instalação do zero no Raspberry Pi](#-instalação-do-zero-no-raspberry-pi)
4. [Ordem para ligar tudo](#-ordem-para-ligar-tudo)
5. [Como operar uma missão](#-como-operar-uma-missão)
6. [Botões e teclas](#-botões-e-teclas)
7. [Mensagens do painel](#-mensagens-do-painel)
8. [Parâmetros do código](#️-parâmetros-do-código)
9. [Como funciona](#-como-funciona)
10. [Segurança e limitações](#-segurança-e-limitações)
11. [Solução de problemas](#-solução-de-problemas)

---

## 🧰 Hardware necessário

| Item | Observação |
|---|---|
| Raspberry Pi 4 Model B (4 GB ou mais) | Testado com Raspberry Pi OS 64-bit (Debian 13 "trixie") |
| **Fonte oficial Raspberry Pi 4 (5,1 V / 3 A, USB-C)** | Fonte fraca ou cabo fino causam subtensão: a CPU cai para 600 MHz e o vídeo atrasa |
| Tela touch oficial Raspberry Pi 7" | Ligada pelo **cabo flat na porta DISPLAY** e alimentada pela **sua própria fonte (micro-USB da tela)** |
| Monitor HDMI | Mostra a imagem da câmera com a detecção da fachada |
| Cartão microSD (32 GB ou mais) | |
| DJI Tello | Bateria carregada |
| Maquete de fachada | Com elementos azuis (pares de varandas) visíveis pela câmera |
| Dissipador + ventoinha para a Pi (recomendado) | Sem refrigeração a Pi chega a ~80 °C em carga e reduz a velocidade |

> ⚠️ **Não alimente a tela pelos pinos 5V/GND da GPIO e por uma fonte externa ao mesmo tempo.** Use só uma das duas. Ligar as duas juntas causou subtensão na Pi e travamento da tela durante os testes.

---

## 🗺️ Como o sistema é organizado

```
┌──────────────────────┐    Wi-Fi (rede TELLO-XXXXXX)    ┌──────────────┐
│   Raspberry Pi 4     │ ◄─────────────────────────────► │  DJI Tello   │
│                      │   comandos UDP 8889             │              │
│  main.py             │   telemetria UDP 8890           │              │
│                      │   vídeo H.264 UDP 11111         │              │
└──────┬────────┬──────┘                                 └──────────────┘
       │        │
  cabo flat    HDMI
       │        │
┌──────▼─────┐ ┌▼──────────────────────────────┐
│ Tela touch │ │ Monitor HDMI                  │
│ 7" (DSI-1) │ │ (HDMI-A-1)                    │
│            │ │                               │
│ Central de │ │ Janela da câmera com a        │
│ controle:  │ │ detecção da fachada           │
│ telemetria │ │ "Tello - Deteccao de Fachada" │
│ e botões   │ │                               │
└────────────┘ └───────────────────────────────┘
```

**Importante:** enquanto o programa está conectado ao drone, a Pi fica na rede Wi-Fi **do Tello**. Nesse período ela **não tem internet** e não fica acessível por SSH pela rede de casa/laboratório.

---

## 🔧 Instalação do zero no Raspberry Pi

Todos os comandos abaixo são executados **no terminal da Raspberry Pi** (ou via SSH) com o usuário `tello`. Se o seu usuário for outro, troque `/home/tello` pelo seu diretório nos arquivos `start_tello.sh` e `deploy/tello-inspector.desktop`.

### 1. Atualizar o sistema

```bash
sudo apt update
sudo apt full-upgrade -y
sudo reboot
```

### 2. Instalar os pacotes do sistema

```bash
sudo apt install -y git python3-venv python3-pip
```

O NetworkManager (`nmcli`), o labwc e o kanshi já vêm instalados no Raspberry Pi OS Desktop.

### 3. Clonar o repositório

```bash
cd ~
git clone https://github.com/AlmeidaJoaoPedro/dji_tellodji_tello_facade_inspection.git
cd ~/dji_tellodji_tello_facade_inspection
```

### 4. Criar o ambiente virtual e instalar as dependências

O script de inicialização espera o ambiente virtual em `~/tello/tello_env`:

```bash
mkdir -p ~/tello
python3 -m venv ~/tello/tello_env
source ~/tello/tello_env/bin/activate
python -m pip install --upgrade pip
python -m pip install -r ~/dji_tellodji_tello_facade_inspection/requirements.txt
```

Para conferir se tudo instalou:

```bash
python -c "import djitellopy, av, cv2, pygame, numpy; print('OK', cv2.__version__, av.__version__)"
```

### 5. Configurar o Wi-Fi do Tello (só na primeira vez)

1. Ligue o Tello e espere ~20 s até a rede dele aparecer.
2. Descubra o nome exato da rede:

   ```bash
   nmcli -f SSID,SIGNAL dev wifi list --rescan yes | grep -i tello
   ```

3. Conecte uma vez para o NetworkManager salvar o perfil (substitua pelo nome que apareceu):

   ```bash
   nmcli dev wifi connect TELLO-CFA143
   ```

4. Coloque **exatamente esse nome** (sem espaços extras) na constante `TELLO_SSID` do `main.py`:

   ```python
   TELLO_SSID = "TELLO-CFA143"
   ```

5. Volte para a rede de casa/laboratório (troque `caramel` pelo nome da sua rede):

   ```bash
   nmcli con up caramel
   ```

> Se o nome em `TELLO_SSID` estiver diferente do nome real da rede (por exemplo `TELLO-CFA 143` com espaço), o botão **RECONECTAR** nunca consegue conectar.

### 6. Configurar a tela touch de 7"

Garanta que o driver da tela seja carregado no boot. Isso evita depender da detecção automática, que pode falhar:

```bash
echo -e '\n[all]\ndtoverlay=vc4-kms-dsi-7inch' | sudo tee -a /boot/firmware/config.txt
sudo reboot
```

Depois do reboot, organize as telas em **Menu → Preferências → Screen Configuration**:

- **DSI-1** (tela touch): rotação **270°** (retrato, 480×800)
- **HDMI-A-1** (monitor): 1920×1080

A configuração fica salva em `~/.config/kanshi/config`. A usada nos testes é esta:

```
profile {
    output HDMI-A-1 enable scale 1.000000 mode 1920x1080@60.000 position 800,0 transform normal
    output DSI-1 enable scale 1.000000 mode 800x480@60.029 position 2720,271 transform 270
}
```

Se mudar as posições, atualize também `RASP_POS_X/Y` e `MONITOR_POS_X/Y` no início do `main.py`.

### 7. Regras de janela (cada janela na tela certa)

O arquivo `deploy/labwc-rc.xml` faz três coisas:

- mapeia o toque da tela para a saída `DSI-1`;
- abre a **central de controle em tela cheia na tela touch** e manda a **câmera para o monitor HDMI** (em tela cheia, pedida pelo próprio OpenCV);
- cria o atalho **F11** para alternar a janela selecionada entre tela cheia e janela, mantendo os atalhos padrão do Raspberry Pi OS.

```bash
cp ~/.config/labwc/rc.xml ~/.config/labwc/rc.xml.bak 2>/dev/null
cp ~/dji_tellodji_tello_facade_inspection/deploy/labwc-rc.xml ~/.config/labwc/rc.xml
labwc --reconfigure
```

> O nome do dispositivo de toque (`10-0038 generic ft5x06 (79)`) pode ser diferente na sua Pi. Confira com `grep Name /proc/bus/input/devices` e ajuste no `rc.xml` se precisar.

### 8. Iniciar o programa automaticamente ao ligar a Pi

```bash
chmod +x ~/dji_tellodji_tello_facade_inspection/start_tello.sh
mkdir -p ~/.config/autostart
cp ~/dji_tellodji_tello_facade_inspection/deploy/tello-inspector.desktop ~/.config/autostart/
```

O `start_tello.sh` espera 5 s até as telas ficarem prontas e roda o `main.py` com o Python do ambiente virtual. A saída vai para `~/tello_inspector.log`.

Para **desativar** o início automático:

```bash
rm ~/.config/autostart/tello-inspector.desktop
```

### 9. Otimizações de desempenho (recomendado)

```bash
# CPU sempre na frequência máxima (governor "performance")
sudo cp ~/dji_tellodji_tello_facade_inspection/deploy/60-cpu-performance.rules /etc/udev/rules.d/

# Wi-Fi sem economia de energia (menor latência com o drone)
sudo cp ~/dji_tellodji_tello_facade_inspection/deploy/wifi-powersave-off.conf /etc/NetworkManager/conf.d/

# Desativar serviços que não são usados
sudo systemctl disable --now bluetooth.service cups.service cups.socket cups.path cups-browsed.service
sudo systemctl disable --now apt-daily.timer apt-daily-upgrade.timer man-db.timer

sudo reboot
```

Para conferir depois do reboot:

```bash
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor   # deve mostrar: performance
vcgencmd get_throttled                                       # deve mostrar: throttled=0x0
```

> Não faça overclock sem dissipador e ventoinha. Nos testes, 1,8 GHz sem refrigeração passou de 85 °C em 15 s e acabou **mais lento** que o padrão.

### 10. Rodar manualmente (sem o início automático)

```bash
cd ~/dji_tellodji_tello_facade_inspection
~/tello/tello_env/bin/python main.py
```

Para rodar a partir de um terminal SSH, antes exporte as variáveis da sessão gráfica:

```bash
export DISPLAY=:0 XAUTHORITY=/home/tello/.Xauthority XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-0
```

---

## 🔌 Ordem para ligar tudo

1. **Monte o cenário:** drone no chão, em área livre e plana, com a maquete à frente e os elementos azuis visíveis.
2. **Ligue a tela touch** na fonte dela e o **monitor HDMI**.
3. **Ligue a Raspberry Pi** com a fonte oficial. A área de trabalho abre e, ~5 s depois, aparecem a **central de controle** (tela touch) e a **janela da câmera** (monitor).
4. **Ligue o Tello** e espere ~20 s até a rede Wi-Fi dele ficar disponível.
5. Na tela touch, toque em **RECONECTAR DRONE / WI-FI** e acompanhe a linha **Rede** até aparecer **"Drone Pronto!"**.

> Se o Tello já estiver ligado quando a Pi iniciar, o programa conecta sozinho. Mesmo assim, ligar a Pi primeiro e o drone depois é a ordem mais previsível.

**Para desligar:** pouse o drone, feche o programa (`ESC` ou ✕ da janela), desligue o Tello e desligue a Pi com:

```bash
sudo poweroff
```

Espere o LED verde da Pi parar de piscar antes de tirar da tomada.

---

## 🎮 Como operar uma missão

1. **Conectar:** toque em **RECONECTAR DRONE / WI-FI** até a linha *Rede* mostrar **"Drone Pronto!"** (em verde). A bateria e a temperatura do drone passam a ser atualizadas e o vídeo aparece no monitor HDMI.
2. **Conferir a detecção:** no monitor, os elementos azuis aparecem com retângulos laranja e o rótulo `FACHADA`. Quando um par alinhado é encontrado, aparecem uma linha amarela ligando o par, um ponto verde no centro e o texto `Centro / Span`. No painel, *Alvo Fachada* muda de **A PROCURAR** para **BLOQUEADO**.
3. **Ajustar a distância desejada (Largura Alvo):** com o teclado, use `+`/`P` para aumentar e `-`/`M` para diminuir (passos de 10 px; valor inicial 600 px). Largura maior faz o drone ficar **mais perto** da fachada.
4. **Decolar:** toque em **DECOLAR / INICIAR** (fica **verde** quando é possível decolar) ou aperte `ESPAÇO`. O drone decola e entra no estado `ASCENDING`.
5. **Durante o voo:**
   - centraliza a fachada na imagem (roll, via PID);
   - avança ou recua para manter a largura alvo (pitch);
   - sobe até o ToF marcar 190 cm (`ASCENDING`), depois desce até 30 cm (`DESCENDING`), e repete.
6. **Pousar:** toque em **POUSAR / PARAR** ou aperte `L`. O drone para e pousa, e o estado volta a `IDLE`.
7. **Trocar a bateria:** pouse, troque a bateria, ligue o Tello e toque em **RECONECTAR** de novo. Não é preciso reiniciar o programa.

> 🔋 Com bateria em **20% ou menos**, o programa **não deixa decolar** e, se estiver voando, **pousa automaticamente**.

---

## 🕹️ Botões e teclas

### Botões da tela touch

| Botão | O que faz |
|---|---|
| **RECONECTAR DRONE / WI-FI** (azul) | Conecta a Pi à rede do Tello (`TELLO_SSID`), abre a conexão de comando com o drone e liga o vídeo. Roda em segundo plano, então a tela não trava. O andamento aparece na linha *Rede*. Use depois de ligar o drone ou trocar a bateria. |
| **DECOLAR / INICIAR** (verde quando disponível, cinza quando bloqueado) | Decola e inicia a inspeção automática. Só funciona com o drone conectado, estado `IDLE` e bateria acima de 20%. |
| **POUSAR / PARAR** (vermelho) | Zera os comandos de movimento e manda o drone pousar. O estado volta a `IDLE`. |

### Teclado (com a janela da central de controle selecionada)

| Tecla | Função |
|---|---|
| `ESPAÇO` | Decolar / iniciar (igual ao botão verde) |
| `L` | Pousar / parar (igual ao botão vermelho) |
| `R` | Reconectar drone / Wi-Fi (igual ao botão azul) |
| `+`, `+` do teclado numérico ou `P` | Aumenta a largura alvo em 10 px (drone fica mais perto) |
| `-`, `-` do teclado numérico ou `M` | Diminui a largura alvo em 10 px (drone fica mais longe) |
| `ESC` | Fecha o programa. Se estiver voando, manda parar e pousar antes de fechar. `ESC` também funciona na janela da câmera. |
| `F11` | Alterna a janela selecionada entre **tela cheia** e **janela** (vale para as duas telas) |

### Telas

As duas telas abrem em **tela cheia**: a central de controle na tela touch e a câmera no monitor HDMI. Para mexer em outras coisas da Pi, selecione a janela e aperte **F11**. Ela vira uma janela normal, com barra de título para minimizar, mover e fechar. Aperte **F11** de novo para voltar à tela cheia. A central de controle se ajusta a qualquer tamanho de janela sem cortar nenhum botão.

---

## 💬 Mensagens do painel

### Linha "Rede"

| Mensagem | Significado / o que fazer |
|---|---|
| `Checando Wi-Fi...` | Início da conexão |
| `Procurando TELLO-XXXX (1/3)...` | Buscando a rede do Tello (até 3 tentativas) |
| `Conectando ao Wi-Fi (1/3)...` | Associando à rede do Tello (espera até 40 s) |
| `Wi-Fi OK: TELLO-XXXX` | Pi conectada à rede do drone |
| `Iniciando video...` | Ligando o vídeo do drone |
| **`Drone Pronto!`** (verde) | Tudo certo: pode decolar |
| `Tello nao encontrado. Drone ligado?` | A rede do Tello não apareceu. Confira se o drone está ligado, espere ~20 s e toque em RECONECTAR. Confira também o `TELLO_SSID`. |
| `Wi-Fi do Tello pediu senha` | A rede do Tello está com senha; configure com `nmcli` |
| `Drone nao respondeu (SDK)` | O Wi-Fi conectou, mas o drone não respondeu ao comando `command`. Reinicie o Tello e reconecte. |
| `Falha no video do Tello` | O drone conectou, mas o vídeo não chegou em 5 s. Toque em RECONECTAR. |

### Outros campos

| Campo | Significado |
|---|---|
| Nível da bateria | Bateria do Tello (%). Verde > 40%, laranja > 20%, vermelho ≤ 20% |
| Temperatura interna | Temperatura do Tello (°C) |
| FSM | Estado da missão: `IDLE` (no chão / parado), `ASCENDING` (subindo), `DESCENDING` (descendo) |
| Altitude ToF | Distância lida pelo sensor ToF (cm) |
| Alvo Fachada | `BLOQUEADO` = par de elementos azuis encontrado; `A PROCURAR` = sem alvo |
| Largura Atual / Largura Alvo | Largura medida da fachada na imagem e a largura desejada (px) |
| Roll / Pitch / V | Últimos comandos enviados: lateral, frontal e vertical |

---

## ⚙️ Parâmetros do código

Ficam no início do `main.py`.

| Parâmetro | Valor | Descrição |
|---|---:|---|
| `TELLO_SSID` | `"TELLO-CFA143"` | Nome **exato** da rede Wi-Fi do seu Tello |
| `FPS` | 10 | Frequência do laço de controle (PID e `send_rc_control`), em Hz |
| `PANEL_FPS` | 5 | Atualizações por segundo da central de controle |
| `VISION_SCALE` | 0.5 | Escala da imagem usada na detecção (0.5 = 480×360, ~4× mais leve) |
| `SPEED_VERT` | 15 | Velocidade vertical de subida/descida (escala do Tello, -100 a 100) |
| `ALT_MIN_TOF` | 30 cm | Limite inferior do ToF: ao chegar aqui, volta a subir |
| `ALT_MAX_TOF` | 190 cm | Limite superior do ToF: ao chegar aqui, começa a descer |
| `CRITICAL_BATTERY` | 20 % | Bateria mínima: bloqueia a decolagem e força o pouso |
| `IMG_CENTER_X` | 480 px | Centro horizontal da imagem (vídeo do Tello: 960×720) |
| `TARGET_SPAN` | 600 px | Largura alvo inicial da fachada |
| `RASP_POS_X/Y`, `RASP_WIDTH/HEIGHT` | 2720, 271, 480, 800 | Posição e tamanho da tela touch no layout do kanshi |
| `MONITOR_POS_X/Y` | 800, 0 | Posição do monitor HDMI no layout do kanshi |

### Controlador PID (alinhamento lateral)

```python
kp = 0.09   ki = 0.008   kd = 0.035
saída limitada a ±16   integral limitada a ±8   zona morta de 6 px
```

### Controle de distância (pitch)

| Diferença `largura atual − largura alvo` | Comando de pitch |
|---|---|
| > +50 px (muito perto) | −12 (recua) |
| +20 a +50 px | −7 (recua devagar) |
| −20 a +20 px | 0 |
| −50 a −20 px | +6 (avança devagar) |
| < −50 px (muito longe) | +9 (avança) |

---

## 🧠 Como funciona

### Vídeo com baixa latência

O leitor padrão do `djitellopy` converte cada quadro pelo PIL (~72 ms por quadro na Pi). Como o Tello envia 30 fps, os quadros acumulavam e o atraso crescia sem parar (chegava a 3,8 s).

O `main.py` usa um leitor próprio (`LowLatencyFrameReader`) que:

- abre o stream sem buffer (`fflags=nobuffer`, `flags=low_delay`);
- decodifica com várias threads (`SLICE`) sem acrescentar atraso;
- guarda **apenas o quadro mais recente** e só converte para RGB o quadro que vai ser exibido.

Resultado medido na Pi: **~25–30 fps exibidos e ~70 ms de processamento**, estável. A isso se soma a latência do próprio Tello e do Wi-Fi (~200–300 ms).

### Detecção da fachada

1. Reduz a imagem para 480×360 (`VISION_SCALE`).
2. Converte para HSV e separa o azul (`H 100–135`, `S 110–255`, `V 50–255`).
3. Aplica fechamento morfológico e extrai contornos.
4. Mantém regiões com área > 300 px (na escala original) e mais largas que altas.
5. Escolhe o par de regiões mais alinhado horizontalmente (diferença vertical < 30 px e distância horizontal > 300 px).
6. Calcula o centro e a largura do par, com suavização temporal (filtro exponencial).

### Máquina de estados vertical

`IDLE` → (decolar) → `ASCENDING` ⇄ `DESCENDING` → (pousar) → `IDLE`

---

## 🔒 Segurança e limitações

Este projeto é experimental e **não** é um sistema de segurança certificado.

- Faça os primeiros testes **sem hélices** para validar a interface, a conexão e o fluxo.
- Voe em área fechada e controlada, sem pessoas, animais ou obstáculos.
- **Mantenha sempre alguém pronto para apertar POUSAR (`L`).** Fechar a janela não é um mecanismo de emergência confiável.
- Confirme o sentido dos comandos de roll e pitch em testes controlados antes de voar perto da maquete.

### Limitações conhecidas

- **Perder o alvo não para o drone por completo:** sem alvo, roll e pitch são zerados, mas a subida/descida automática **continua**.
- O ToF mede a distância até a superfície abaixo do drone, o que pode não ser a altura real em relação ao chão.
- A largura em pixels é uma referência relativa, não uma distância em centímetros.
- Iluminação, reflexos, sombras e outros objetos azuis afetam a detecção.
- Não há detecção de obstáculos nem prevenção de colisões.

---

## 🐛 Solução de problemas

### Ver o log do programa

```bash
tail -f ~/tello_inspector.log
```

As linhas `[WIFI]`, `[SISTEMA]`, `[ERRO]` e `[VIDEO]` mostram o motivo exato das falhas.

### O botão RECONECTAR nunca conecta

1. Confira se o drone está ligado e se a rede dele aparece:

   ```bash
   nmcli -f SSID,SIGNAL dev wifi list --rescan yes | grep -i tello
   ```

2. Confira se o nome que aparece é **idêntico** ao `TELLO_SSID` do `main.py`.
3. Veja o erro no log (`grep WIFI ~/tello_inspector.log`).

### Voltar para a rede de casa/laboratório (internet e SSH)

Pelo ícone de Wi-Fi da barra de tarefas, ou:

```bash
nmcli con up caramel   # troque pelo nome da sua rede
```

### A tela touch ficou apagada ou o toque não funciona

- Desligue a Pi (`sudo poweroff`), **tire a fonte da tomada e a fonte da tela** por ~15 s e ligue de novo. Um reboot simples não destrava a controladora da tela.
- Confira se o cabo flat está bem encaixado nos dois lados, com a trava fechada.
- Confira no log do kernel:

  ```bash
  dmesg | grep -iE 'backlight|ft5x06|touchscreen'
  ```

  Mensagens `failed to enable backlight: -5` ou `touchscreen probe failed` indicam falta de energia ou cabo mal encaixado.

### O vídeo está atrasando ou a Pi está lenta

```bash
vcgencmd get_throttled     # 0x0 = normal
vcgencmd measure_temp
```

| Valor de `get_throttled` | Causa |
|---|---|
| `0x0` | Tudo normal |
| `0x50005` / `0x50000` | **Subtensão**: troque o cabo USB-C ou use a fonte oficial |
| `0x80008` / `0xe0008` | **Temperatura** alta: instale dissipador e ventoinha |

### Módulo não encontrado (`djitellopy`, `cv2`, `pygame`, `av`)

```bash
source ~/tello/tello_env/bin/activate
python -m pip install -r ~/dji_tellodji_tello_facade_inspection/requirements.txt
```

### O programa não abre sozinho no boot

```bash
cat ~/.config/autostart/tello-inspector.desktop
ls -l ~/dji_tellodji_tello_facade_inspection/start_tello.sh   # precisa ter permissão de execução (x)
tail -n 50 ~/tello_inspector.log
```

### As janelas abrem na tela errada

Confira os nomes das saídas com `wlr-randr` (devem ser `DSI-1` e `HDMI-A-1`) e ajuste o `~/.config/labwc/rc.xml`. Depois rode `labwc --reconfigure`.

### O drone não decola

- A linha *Rede* precisa mostrar **"Drone Pronto!"**.
- A bateria precisa estar **acima de 20%**.
- O estado (FSM) precisa ser `IDLE`.

---

## 📂 Estrutura do repositório

```
dji_tellodji_tello_facade_inspection/
├── main.py                        # Aplicação (visão, controle, interface)
├── start_tello.sh                 # Script chamado no boot pelo autostart
├── requirements.txt               # Dependências Python (versões testadas)
├── README.md
└── deploy/
    ├── labwc-rc.xml               # → ~/.config/labwc/rc.xml (toque, tela cheia, atalho F11)
    ├── tello-inspector.desktop    # → ~/.config/autostart/ (início automático)
    ├── 60-cpu-performance.rules   # → /etc/udev/rules.d/ (CPU em modo performance)
    └── wifi-powersave-off.conf    # → /etc/NetworkManager/conf.d/ (Wi-Fi sem economia)
```

## 👨‍💻 Autor

Projeto experimental de visão computacional, controle PID e inspeção autônoma de fachadas com o DJI Tello.
