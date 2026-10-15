# 🚁 DJI Tello Autonomous Façade Inspection

Sistema de inspeção vertical autônoma e rastreamento visual de fachadas prediais utilizando o drone DJI Tello, Python, OpenCV e controle em malha fechada com PID.

## 📌 Visão Geral

O projeto implementa um sistema de *Visual Servoing* para o posicionamento e a inspeção vertical de fachadas de edifícios em escala reduzida.

Utilizando a câmera frontal do DJI Tello, o sistema identifica pares de elementos azuis na fachada, calcula o centro geométrico do alvo e estima sua largura em pixels. Essas informações são utilizadas para controlar o posicionamento lateral e a distância frontal do drone.

Simultaneamente, uma máquina de estados controla a movimentação vertical com base nas leituras do sensor de distância Time-of-Flight (ToF).

Uma interface gráfica desenvolvida com Pygame apresenta a imagem da câmera, as informações de telemetria e os controles da missão.

### ✨ Principais funcionalidades

- **Rastreamento visual:** detecção de elementos azuis da fachada utilizando segmentação HSV e operações morfológicas com OpenCV.
- **Centralização lateral:** controlador PID com termos proporcional, integral e derivativo para reduzir o erro entre o centro da fachada e o centro da imagem.
- **Controle de distância frontal:** estimativa da distância relativa por meio da largura aparente da fachada em pixels.
- **Inspeção vertical automática:** alternância entre subida e descida utilizando o sensor ToF.
- **Filtragem das medições:** suavização temporal das estimativas do centro e da largura do alvo.
- **HUD interativo:** exibição da imagem da câmera, bateria, altitude estimada pelo ToF, comandos de controle e estado da máquina de estados.
- **Ajuste de distância:** alteração da largura-alvo diretamente pelo teclado.
- **Monitoramento de bateria:** tentativa de pouso automático quando a bateria atinge o limite crítico configurado.
- **Controles manuais:** comandos para iniciar a decolagem, solicitar o pouso e encerrar a aplicação.

## 🛠️ Tecnologias utilizadas

- Python 3.10+
- [DJITelloPy](https://github.com/damiafuentes/DJITelloPy)
- [OpenCV](https://opencv.org/)
- [Pygame](https://www.pygame.org/)
- [NumPy](https://numpy.org/)

## 📋 Requisitos

Antes de executar o projeto, certifique-se de possuir:

- Python 3.10 ou superior.
- Um drone DJI Tello compatível com a biblioteca DJITelloPy.
- Um computador com conexão Wi-Fi.
- Uma maquete de fachada com elementos azuis visíveis pela câmera.
- Bateria suficiente para realizar os testes com segurança.

## 🚀 Instalação e configuração

### 1. Clonar o repositório

git clone https://github.com/AlmeidaJoaoPedro/dji_tello_facade_inspection.git cd djitellofacade_inspection


### 2. Criar um ambiente virtual

**Linux / macOS:**

python3 -m venv venv source venv/bin/activate


**Windows — Prompt de Comando (CMD):**

python -m venv venv venv\Scripts\activate.bat


**Windows — PowerShell:**

python -m venv venv .\venv\Scripts\Activate.ps1


### 3. Atualizar o pip

python -m pip install --upgrade pip


### 4. Instalar as dependências

python -m pip install djitellopy opencv-python pygame numpy

## 🎮 Como operar

### 1. Preparar o ambiente

- Posicione o drone em uma área livre, plana e segura.
- Coloque a maquete da fachada à frente do drone.
- Certifique-se de que os elementos azuis da fachada estejam visíveis pela câmera.
- Mantenha distância suficiente de paredes, pessoas, objetos e outros obstáculos.
- Verifique se a bateria está carregada.

### 2. Conectar ao DJI Tello

Ligue o drone e conecte o computador à rede Wi-Fi emitida por ele, normalmente identificada como `TELLO-CFA146`.

Mantenha a conexão Wi-Fi durante toda a execução do programa.

### 3. Executar a aplicação

Com o ambiente virtual ativado e o terminal aberto na pasta do projeto, execute:

python main.py


No Linux, caso necessário, utilize `python3 main.py`.

### 4. Calibrar o rastreamento visual

Ao abrir a interface gráfica, verifique se o sistema consegue identificar os elementos azuis da fachada.

A interface apresenta informações como:

- Imagem capturada pela câmera.
- Marcações dos elementos identificados.
- Centro estimado da fachada.
- Largura aparente do alvo em pixels.
- Estado do rastreamento.
- Nível da bateria.
- Distância informada pelo sensor ToF.
- Comandos laterais e frontais enviados ao drone.
- Estado atual da máquina de estados.

O rastreamento depende da visibilidade dos elementos azuis. Iluminação, reflexos, oclusões e objetos com cores semelhantes podem afetar a detecção.

### 5. Ajustar a distância desejada

Antes da decolagem, utilize as teclas abaixo para ajustar a largura-alvo da fachada:

| Tecla | Função |
|---|---|
| `+` | Aumenta a largura-alvo em 10 pixels. |
| `-` | Diminui a largura-alvo em 10 pixels. |

O valor inicial é de 600 pixels.

A largura em pixels é uma referência visual relativa, não uma medição direta em centímetros. O resultado depende da geometria da fachada, da câmera e da orientação do drone.

### 6. Iniciar a missão

Quando o ambiente estiver preparado e o rastreamento visual estiver funcionando, pressione:

- `ESPAÇO`; ou
- Clique no botão **DECOLAR / INICIAR**.

O programa solicita a decolagem e inicia a máquina de estados de movimentação vertical.

Durante a execução, o drone tenta:

1. Manter o centro da fachada alinhado ao centro da imagem.
2. Ajustar a distância frontal com base na largura aparente do alvo.
3. Alternar entre subida e descida de acordo com as leituras do sensor ToF.
4. Atualizar continuamente a interface gráfica e a telemetria.

### 7. Solicitar o pouso

Para solicitar o pouso, pressione:

- `L`; ou
- Clique no botão **POUSAR / PARAR**.

O programa envia comandos de velocidade zero e solicita o pouso do drone.

**Importante:** o comando `L` solicita o pouso; ele não representa apenas uma pausa da missão.

### 8. Encerrar a aplicação

Para encerrar a janela, pressione `ESC` ou feche a interface gráfica.

O código tenta interromper os comandos de movimento, solicitar o pouso, encerrar a transmissão de vídeo e finalizar o Pygame.

Por segurança, não utilize o encerramento da janela como único mecanismo de emergência. Mantenha o drone sob supervisão e esteja preparado para intervir manualmente.

## ⚙️ Parâmetros de controle

Os principais parâmetros podem ser encontrados no início do arquivo `main.py`.

| Parâmetro | Valor inicial | Descrição |
|---|---:|---|
| `FPS` | 60 | Frequência de atualização configurada para o controle e a interface. |
| `SPEED_VERT` | 30 | Intensidade do comando de subida ou descida. |
| `ALT_MIN_TOF` | 30 cm | Limite inferior configurado para a distância medida pelo ToF. |
| `ALT_MAX_TOF` | 190 cm | Limite superior configurado para a distância medida pelo ToF. |
| `CRITICAL_BATTERY` | 20% | Limite de bateria considerado crítico. |
| `IMG_CENTER_X` | 480 px | Centro horizontal esperado para uma imagem de 960 pixels de largura. |
| `TARGET_SPAN` | 600 px | Largura aparente desejada para a fachada. |

### Controlador PID

O alinhamento lateral utiliza um controlador PID com os seguintes ganhos iniciais:

kp = 0.09 ki = 0.008 kd = 0.035


O controlador inclui limitação da saída e do termo integral para reduzir a saturação e o acúmulo excessivo da integral (*integral windup*).

A zona morta lateral é de 6 pixels: quando o erro absoluto está dentro desse limite, o comando lateral é zerado.

Os ganhos foram definidos no código como valores iniciais e devem ser validados experimentalmente em um ambiente controlado.

### Máquina de estados vertical

A movimentação vertical utiliza dois estados principais:

- `ASCENDING`: comanda a subida até atingir o limite superior configurado.
- `DESCENDING`: comanda a descida até atingir o limite inferior configurado.

Ao atingir um dos limites, o sistema alterna para o estado oposto.

O sensor ToF mede a distância até a superfície detectada, que pode não corresponder à altitude real em relação ao solo dependendo da orientação do sensor e dos objetos presentes no ambiente.

## 🧠 Como funciona o rastreamento visual

O processamento de imagem utiliza as seguintes etapas:

1. Conversão da imagem para o espaço de cores HSV.
2. Segmentação da faixa de azul definida no código.
3. Aplicação de fechamento morfológico para melhorar a continuidade das regiões detectadas.
4. Extração de contornos.
5. Filtragem de regiões com área superior a 300 pixels.
6. Seleção de pares de regiões aproximadamente alinhadas horizontalmente.
7. Estimativa do centro e da largura aparente da fachada.
8. Filtragem temporal das medições para reduzir oscilações.

O algoritmo utiliza as coordenadas dos elementos detectados para calcular o erro de centralização.

A largura aparente é comparada com a largura-alvo para determinar se o drone deve avançar, recuar ou manter o comando frontal zerado.

## 🔒 Segurança e limitações

Este projeto é experimental e não deve ser considerado um sistema de segurança certificado.

Antes de realizar qualquer voo:

- Teste o programa sem hélices, quando apropriado, para verificar a interface e o fluxo de execução.
- Realize os primeiros testes de voo em uma área aberta e controlada.
- Mantenha supervisão direta durante toda a operação.
- Utilize uma área livre de pessoas, animais e obstáculos.
- Não dependa exclusivamente da visão computacional para evitar colisões.
- Verifique o comportamento do sensor ToF antes de habilitar a movimentação vertical.
- Confirme que a fachada pode ser identificada de maneira consistente.
- Teste o pouso manual antes de iniciar uma missão autônoma.

### Limitações conhecidas

- O rastreamento depende da identificação de elementos azuis com dimensões e alinhamento compatíveis com os filtros implementados.
- A largura em pixels não fornece uma distância física absoluta.
- O sensor ToF pode apresentar leituras inválidas ou depender da superfície observada.
- A perda do alvo interrompe o cálculo normal dos comandos de alinhamento, mas não garante, por si só, uma parada completa do drone.
- O limite de bateria crítica não substitui o monitoramento contínuo do operador.
- O programa não implementa uma verificação completa de obstáculos nem um sistema independente de prevenção de colisões.
- A estabilidade do controle depende das condições de iluminação, da qualidade da detecção e das características do ambiente.

## 🐛 Solução de problemas

### O módulo `djitellopy` não foi encontrado

Ative o ambiente virtual e execute:

python -m pip install djitellopy


### O módulo `cv2` não foi encontrado

Execute:

python -m pip install opencv-python


### O módulo `pygame` não foi encontrado

Execute:

python -m pip install pygame


### O drone não conecta

1. Verifique se o DJI Tello está ligado.
2. Confirme se o computador está conectado à rede Wi-Fi do drone.
3. Verifique se outro programa não está utilizando a conexão.
4. Reinicie o drone e tente novamente.

### A fachada não é identificada

- Verifique se os elementos azuis estão visíveis.
- Melhore a iluminação do ambiente.
- Evite reflexos intensos e sombras excessivas.
- Confira se os elementos detectados são suficientemente grandes.
- Verifique se existem pelo menos duas regiões compatíveis com os critérios de alinhamento e separação definidos no código.

### O programa não inicia a decolagem

Verifique a conexão com o drone e o nível da bateria.

O código impede a decolagem quando a bateria reportada é menor ou igual a 20%.

## 📄 Licença

Este projeto pode ser distribuído sob uma licença de código aberto, desde que uma licença apropriada seja definida e incluída no repositório.

## 👨‍💻 Autor

Desenvolvido como projeto experimental de visão computacional, controle PID e inspeção autônoma de fachadas utilizando o DJI Tello.

Antes de publicar no GitHub: três detalhes importantes

Revisei a documentação com base no código que você enviou. Há três pontos que vale a pena observar para que o README não prometa funcionalidades que ainda não estão implementadas.
1. A câmera precisa fornecer a resolução esperada

Seu código define:

IMG_CENTER_X = 960 // 2

Isso pressupõe que a imagem tenha 960 pixels de largura. Se a resolução efetiva for diferente, o centro usado pelo controlador poderá não corresponder ao centro real da imagem.

Além disso, o código define a altura da interface como 720 pixels, mas não redimensiona explicitamente o quadro recebido da câmera antes de desenhá-lo.
2. A perda do alvo não interrompe todos os movimentos

Quando a fachada deixa de ser detectada, o programa zera os comandos de roll e pitch calculados naquele ciclo, mas mantém o comando vertical da máquina de estados.

Isso significa que o drone pode continuar subindo ou descendo mesmo sem o alvo visual. Portanto, não seria correto afirmar que o código garante uma parada completa em caso de perda de rastreamento.
3. O limite do sensor ToF não representa necessariamente a altura em relação ao solo

O código utiliza:

ALT_MIN_TOF = 30
ALT_MAX_TOF = 190

Esses valores são comparados diretamente com get_distance_tof(). A distância medida depende da superfície observada pelo sensor, de sua orientação e das condições do ambiente.

Por isso, a documentação descreve esses parâmetros como limites de distância do ToF, e não como uma medição garantida da altitude real.

Minha recomendação: antes de executar uma missão autônoma, valide especialmente a direção dos comandos de roll e pitch, o comportamento vertical e a resposta à perda do alvo. O código envia comandos de velocidade ao drone, e os sinais devem ser confirmados em testes controlados antes de qualquer operação próxima à maquete.
