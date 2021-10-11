# Programa para ler condicoes ambientais do termohigrometro
# Rotronic Hygropalm 2 via interface RS-232
# Autor: Gean M. Geronymo
# Data: 20/04/2016
# Última atualizacao: 10/02/2021
# removida interface direta com postgresql - salvar apenas via http na API REST

# funcoes

def log_txt(ano,data,hora,humidity,temperature):
    # escrever em arquivo texto (compatibilidade com versao antiga)
    with open("Log_"+ano+".txt","a") as text_file:
        print("{}\t{}\t{}%\t{}ºC".format(data,hora,int(humidity),temperature), file=text_file)
        text_file.close();
    # escrever a ultima leitura no arquivo TermHigr.dat
    # compatibilidade com o programa de medicao
    with open("TermHigr.dat","w") as text_file:
        print("{}\n{}\n{}\n{}".format(data,hora,int(humidity),temperature), file=text_file)
        text_file.close();

    return

def write_buffer(filename,temperature,humidity,timestamp,certificado,data_certificado):
    # filename: string com o nome do arquivo de buffer
    with open(filename,"a") as csvfile:
        write_buffer = csv.writer(csvfile, delimiter=',',lineterminator='\n')
        write_buffer.writerow([str(temperature),str(humidity),timestamp,certificado,data_certificado])
        csvfile.close();
    return

def open_buffer(filename):
    with open(filename) as csvfile:
        reader = csv.DictReader(csvfile,delimiter=',',fieldnames=['temperature','humidity','date','certificado','data_certificado'])
        d = list(reader)
        csvfile.close();
    return d

def data_hora():
    date = datetime.datetime.now();
    timestamp = datetime.datetime.strftime(date, '%Y-%m-%d %H:%M:%S')
    data = datetime.datetime.strftime(date, '%d/%m/%Y')
    hora = datetime.datetime.strftime(date, '%H:%M:%S')
    ano = datetime.datetime.strftime(date, '%Y')
    return {'timestamp':timestamp, 'data':data, 'hora':hora, 'ano':ano}

def dberror_log(timestamp):
    import traceback
    with open("dberror.log","a") as text_file:
        print("{}   Erro ao conectar com o banco de dados \n".format(timestamp), file=text_file)
        traceback.print_exc(file=text_file)
        text_file.close();
    return

def corr_temp(cal):
    # calcula correcoes para temperatura
    x_temperature = cal['Temperatura']['indicacoes'].split(',');
    x_temperature = array([float(a) for a in x_temperature]);
    temperature_correcoes = cal['Temperatura']['correcoes'].split(',');
    temperature_correcoes = array([float(a) for a in temperature_correcoes]);
    y_temperature = x_temperature + temperature_correcoes;
    # minimos quadrados
    A = vstack([x_temperature, ones(len(x_temperature))]).T;
    a, b = linalg.lstsq(A, y_temperature)[0]
    # temperature = a1*x + b1
    return {'a':a, 'b':b}

def corr_umid(cal):
    # calcula correcoes para a umidade
    x_humidity = cal['Umidade']['indicacoes'].split(',');
    x_humidity = array([float(a) for a in x_humidity]);
    humidity_correcoes = cal['Umidade']['correcoes'].split(',');
    humidity_correcoes = array([float(a) for a in humidity_correcoes]);
    y_humidity = x_humidity + humidity_correcoes;
    # minimos quadrados
    A = vstack([x_humidity, ones(len(x_humidity))]).T;
    a, b = linalg.lstsq(A, y_humidity)[0]
    # humidity = a2*x + b2
    return {'a':a, 'b':b}

def query_serial(serialconfig):
    # configuracao da conexao serial
    # seguindo informacoes do manual do fabricante
    ser = serial.Serial(
        port=serialconfig['port'],
        baudrate=19200,
        parity=serial.PARITY_EVEN,
        stopbits=serial.STOPBITS_ONE,
        bytesize=serial.SEVENBITS,
        timeout = int(serialconfig['timeout'])
    )

    querystring = serialconfig['querystring']
    # envia para o termohigrometro a query string com o terminador de linha \r
    #ser.write(b'{u00RDD}\r')
    ser.write((querystring+'\r').encode())

    # le a resposta do termohigrometro
    rcv_str = ser.read(50)
    # fecha a conexao serial
    ser.close()

    # transformar o byte object recebido em uma string
    dec_str = rcv_str.decode('utf-8')
    # processa a string para extrair os valores de temperatura e umidade
    # o termohigrometro retorna uma string do tipo:
    # '{u00RDD 0071.68;0022.78;----.--;----.--;#6\r'
    # o comando abaixo remove o trecho
    # '{u00RDD '
    # Assim, e possivel separar temperatura e umidade utilizando ';'
    data_array = (dec_str.replace(querystring.replace('}',' '),'')).split(';')
    # arredonda a temperatura e umidade para uma casa decimal
    #temperature = round(float(data_array[1]),1)
    #humidity = round(float(data_array[0]),1)
    return data_array

def salvar_http(date, temperature, humidity, cal, url, api_key):
    # dados do certificado de calibracao do termohigrometro
    certificado = cal['Certificado']['certificado']
    data_certificado = cal['Certificado']['data']
    # escreve no buffer de saida
    write_buffer("http_buffer.txt",temperature,humidity,date,certificado,data_certificado)
    try:
        d = open_buffer("http_buffer.txt")
        for leitura in d:
            post_fields = {
                'temperature' : leitura['temperature'],
                'humidity' : leitura['humidity'],
                'date' : leitura['date'],
                'certificado' : leitura['certificado'],
                'data_certificado' : leitura['data_certificado']
            }
            request = Request(url, urlencode(post_fields).encode())
            request.add_header('X-API-KEY', api_key)
            # tenta enviar os dados via http 
            json = urlopen(request).read().decode()
            # apaga o buffer
            open('http_buffer.txt','w').close()
    except:
        dberror_log(data_atual['timestamp'])
    return

# programa principal
if __name__ == "__main__":

    # carrega as bibliotecas necessarias
    from numpy import array, linalg, arange, ones, vstack 
    import serial       # interface RS-232
    import time
    import datetime     # funcoes de data e hora
    import configparser # ler arquivo de configuracao
    import csv          # salvar dados antes de enviar ao DB
    from urllib.parse import urlencode
    from urllib.request import Request, urlopen  # requests http

    # o arquivo settings.ini reune as configuracoes que podem ser alteradas

    config = configparser.ConfigParser()    # iniciar o objeto config
    config.read('settings.ini')             # ler o arquivo de configuracao

    # configuracao para acessar o REST Server
    url = config['HttpConfig']['url']
    api_key = config['HttpConfig']['api_key']

    # o arquivo cal.ini reune as informacoes da calibracao do termohigrometro
    cal = configparser.ConfigParser()
    cal.read('cal.ini')

    # calcular correcoes temperatura
    coeff_temp = corr_temp(cal)

    # calcular correcoes umidade
    coeff_umid = corr_umid(cal)

    data_array = query_serial(config['SerialConfig'])

    # valores corrigidos com o certificado de calibracao
    temperature = round((coeff_temp['a']*float(data_array[1]) + coeff_temp['b']),1)
    humidity = round((coeff_umid['a']*float(data_array[0]) + coeff_umid['b']),1)

    # data e hora
    data_atual = data_hora();
    
    # escrever em arquivo texto (compatibilidade com versao antiga)
    log_txt(data_atual['ano'],data_atual['data'],data_atual['hora'],humidity,temperature)

    # salvar no banco de dados (via API REST)
    salvar_http(data_atual['timestamp'], temperature, humidity, cal, url, api_key)

