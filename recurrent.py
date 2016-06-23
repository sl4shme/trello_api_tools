import config

from apscheduler.schedulers.blocking import BlockingScheduler
from croniter import croniter
from datetime import datetime
import json
import logging
import re
import trello


class Recurrent_job():
    def __init__(self, doc, scheduler, client):
        self.doc = doc
        self.scheduler = scheduler
        self.client = client
        self.create()

    def execute(self):
        try:
            dest_board = [i for i in self.client.list_boards()
                          if i.name == self.doc['to_board']][0]
        except:
            raise Exception("Could not find destination board {}".format(
                            self.doc['to_board']))
        try:
            dest_list = [i for i in dest_board.all_lists()
                         if i.name == self.doc['to_list']][0]
        except:
            raise Exception("Could not find destination list {}".format(
                            self.doc['to_list']))

        new_card = dest_list.add_card(self.doc['card_name'],
                                      source=self.doc['card_id'])
        croni = croniter(self.doc['cron'], datetime.now())
        new_card.set_due(croni.get_next(datetime))


    def create(self):
        cron = self.doc['cron'].split()
        self.scheduler.add_job(self.execute, 'cron', id=self.doc['comment_id'],
                               minute=cron[0], hour=cron[1], day=cron[2],
                               month=cron[3], day_of_week=cron[4])
        logging.info("Created job: {}".format(self.doc))

    def remove(self):
        self.scheduler.remove_job(self.doc['comment_id'])
        logging.info("Removed job: {}".format(self.doc))



class RecurrentTrello():
    def __init__(self):
        self.load_config()
        if self.log_debug:
            logging.basicConfig(filename=self.log_file,  level=logging.DEBUG,
            format='%(asctime)s %(name)s %(levelname)s %(message)s')
        else:
            logging.basicConfig(filename=self.log_file,  level=logging.INFO,
            format='%(asctime)s %(name)s %(levelname)s %(message)s')
        logging.getLogger("requests").setLevel(logging.WARNING)
        logging.getLogger("requests_oauthlib").setLevel(logging.WARNING)
        logging.getLogger("oauthlib").setLevel(logging.WARNING)
        logging.getLogger("apscheduler").setLevel(logging.INFO)
        self.client = trello.TrelloClient(api_key=self.api_key,
                                          api_secret=self.api_secret,
                                          token=self.api_token)
        self.scheduler = BlockingScheduler()
        self.jobs = {}
        self.scheduler.add_job(self.parse_all_comments, 'interval',
                                id='trello_poll', minutes=self.poll_interval)
        self.scheduler.start()

    def load_config(self):
        self.api_key = config.api_key
        self.api_secret = config.api_secret
        self.api_token = config.api_token
        self.recurrent_board_regex = config.recurrent_board_regex
        self.recurrent_list_regex = config.recurrent_list_regex
        self.recurrent_prefix = config.recurrent_prefix
        self.link_board_regex = config.link_board_regex
        self.link_list_regex = config.link_list_regex
        self.link_prefix = config.link_prefix
        self.poll_interval = config.poll_interval
        self.log_file = config.log_file
        self.log_debug = config.log_debug

    def parse_all_comments(self):
        recurrents = []
        for board in self.client.list_boards():
            if board.closed:
                continue
            for tlist in board.all_lists():
                if tlist.closed:
                    continue
                for card in tlist.list_cards():
                    links = []
                    for attempt in range(5):
                        try:
                            card.fetch()
                        except Exception as e:
                            ex = e
                        else:
                            break
                    else:
                        raise(e)
                    for comment in card.comments:
                        if comment['data']['text'].lower().startswith(
                            self.recurrent_prefix.lower()):
                            if (re.match(self.recurrent_list_regex, tlist.name)
                                and re.match(self.recurrent_board_regex,
                                             board.name)):
                                try:
                                    recurrents.append(
                                        self.parse_recurrent_comment(comment))
                                except:
                                    continue

                        elif comment['data']['text'].lower().startswith(
                            self.link_prefix.lower()):
                            if (re.match(self.link_list_regex, tlist.name)
                                and re.match(self.link_board_regex, 
                                             board.name)):
                                links.extend(self.parse_link_comment(comment))
                    if links != []:
                        if len(card.checklists) == 0:
                            card.add_checklist('links', links)
                            logging.info("Added {} links to card {}.".format(
                                len(links), card.name))
                        else:
                            clist = card.checklists[0]
                            clist_items = [i['name'] for i in 
                                           clist.items]
                            to_add = list(set(links).difference(
                                          set(clist_items)))
                            for title in to_add:
                                clist.add_checklist_item(title)
                            if len(to_add) > 0:
                                logging.info("Added {} links to"
                                             "card {}.".format(len(to_add),
                                                               card.name))
        self.update_jobs(recurrents)

    def update_jobs(self, upstream):
        for item in upstream:
            job = self.jobs.get(item['comment_id'])
            if job:
                if job.doc == item:
                    continue
                else:
                    job.remove()
                    self.jobs[item['comment_id']] = Recurrent_job(item,
                                                        self.scheduler,
                                                        self.client)
            else:
                self.jobs[item['comment_id']] = Recurrent_job(item,
                                                    self.scheduler,
                                                    self.client)
        to_delete = set(self.jobs.keys()).difference(
                        set([i['comment_id'] for i in upstream]))

        for job_id in to_delete:
            j = self.jobs.pop(job_id)
            j.remove()

    def parse_link_comment(self, comment):
        text = comment['data']['text'][len(self.link_prefix):]
        text = "".join(i for i in text if ord(i)<128)
        lines = text.splitlines()
        checklist_items = []
        skip = False
        for count, line in enumerate(lines):
            if skip:
                skip = False
                continue
            line = line.strip()
            if line != "":
                if re.match("^(http)|(https)://", line):
                    checklist_items.append(line)
                elif re.match("^(http)|(https)://", lines[count + 1]):
                    checklist_items.append("[{}]({})".format(line,
                                                             lines[count + 1]))
                    skip = True
        return checklist_items

    def parse_recurrent_comment(self, comment):
        text = comment['data']['text'][len(self.recurrent_prefix):]
        text = "".join(i for i in text if ord(i)<128)
        try:
            j = json.loads(text)
        except:
            logging.info("Comment {} does not contain valid"
                         " json.".format(comment['id']))
            raise
        if not re.match("^(\S+ ){4}\S+$", j['cron']):
            logging.info("Comment {} does not contain a valid"
                         " cron.".format(comment['id']))
            raise
        try:
            recurrent = {
                "board_name": comment['data']['board']['name'],
                "board_id": comment['data']['board']['id'],
                "list_name": comment['data']['list']['name'],
                "list_id": comment['data']['list']['id'],
                "card_name": comment['data']['card']['name'],
                "card_id": comment['data']['card']['id'],
                "comment_id": comment['id'],
                "cron": j['cron'],
                "to_board": j['to_board'],
                "to_list": j['to_list']
            }
        except KeyError:
            logging.info("Comment {} is missing some"
                         "field.".format(comment['id']))
            raise
        if (recurrent['board_name'] == recurrent['to_board'] and
                recurrent['list_name'] == recurrent['to_list']):
            logging.debug("Ignoring comment {}. It is an instance of a"
                          " recurrent card".format(comment['id']))
            raise
        return recurrent


