#-*- coding: utf-8 -*-
import sys
import json
import trello
import logging
sys.path.append('/home/trello/code/')
import config


def init():
    if config.log_debug:
        logging.basicConfig(filename=config.log_file_wsgi, level=logging.DEBUG,
        format='%(asctime)s %(name)s %(levelname)s %(message)s')
    else:
        logging.basicConfig(filename=config.log_file_wsgi,  level=logging.INFO,
        format='%(asctime)s %(name)s %(levelname)s %(message)s')
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests_oauthlib").setLevel(logging.WARNING)
    logging.getLogger("oauthlib").setLevel(logging.WARNING)

    api_key = config.api_key
    api_secret = config.api_secret
    api_token = config.api_token
    client = trello.TrelloClient(api_key=api_key,
                                 api_secret=api_secret,
                                 token=api_token)
    return client


def parse_comments(card):
    json_prefix = "data: "
    valid = []
    for comment in card.get_comments():
        try:
            if comment['data']['text'].lower().startswith(json_prefix):
                text = comment['data']['text'][len(json_prefix):]
                valid.append(json.loads(text))
        except:
            pass
    if len(valid) == 1:
        return valid[0]
    else:
        return None


def done(card_id, client):
    card = client.get_card(card_id)
    data = parse_comments(card)
    main_done = [i for i in card.board.all_lists() if "DONE" in i.name][0]
    if card.trello_list.id != main_done.id:
        card.change_list(main_done.id)
    if data is not None:
        dboard = client.get_board(data["source_board"]["id"])
        dlist = [i for i in dboard.all_lists() if "DONE" in i.name][0]
        dlist.add_card(card.name, source=card.id)
    logging.info("Action 'done' on card id: {}".format(card_id))


def backlog(card_id, client):
    card = client.get_card(card_id)
    data = parse_comments(card)
    if data is not None and card.trello_list.id != data["source_board"]["id"]:
        card.change_board(data["source_board"]["id"],
                          data["source_list"]["id"])
    logging.info("Action 'backlog' on card id: {}".format(card_id))


def inbox(card_id, client):
    card = client.get_card(card_id)
    try:
        dest_board = [i for i in client.list_boards()
                      if i.name == card.board.name.split(":")[0] + ": Main"][0]
    except:
        raise Exception("Could not find a corresponding 'Main' board.")

    try:
        dest_list = [i for i in dest_board.all_lists() if "INBOX" in i.name][0]
    except:
        raise Exception("Could not find 'INBOX' list on destination board.")

    if dest_board.id == card.board.id:
        raise Exception("Already on the right board.")

    card.change_board(dest_board.id, dest_list.id)
    data = {"source_board": {"name": card.board.name,
                              "id": card.board.id},
            "source_list": {"name": card.trello_list.name,
                              "id": card.trello_list.id}}
    card.comment('Data: {}'.format(json.dumps(data)))
    logging.info("Action 'inbox' on card id: {}".format(card_id))


def wsgi_app(environ, start_response):
    try:
        client = init()
    	params = {}
        for couple in environ['QUERY_STRING'].split('&'):
            params[couple.split("=")[0]] = couple.split("=")[1]
    	logging.debug("Got request: {}".format(params))
        if params.pop('pkey') != config.PRIVATE_KEY:
            raise Exception("Incorrect private key.")
        if params['action'] == "inbox":
            inbox(params["cardid"], client)
        elif params['action'] == "done":
            done(params["cardid"], client)
        elif params['action'] == "backlog":
            backlog(params["cardid"], client)
        else:
            raise Exception("Incorrect action.")
        resp = {"okay": "OK", "params": params}
        output = '{}({})'.format(params.pop("callback"), json.dumps(resp)).encode('utf8')

    except Exception as e:
        output = "error_callback({})".format(json.dumps(str(e))).encode('utf8')

    logging.debug("Response: {}".format(output))
    status = '200 OK'
    headers = [('Content-type', 'text/plain'),
               ('Content-Length', str(len(output)))]
    start_response(status, headers)
    yield output

application = wsgi_app
