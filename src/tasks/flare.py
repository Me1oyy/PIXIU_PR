"""
FLARE
"""
from itertools import zip_longest
from lm_eval.base import MultipleChoiceTask, Task, rf
from lm_eval.metrics import mean, matthews_corrcoef
import numpy as np
from .utils import process_text
from seqeval.metrics import f1_score as entity_score
from sklearn.metrics import accuracy_score, f1_score


_CITATION = """
@misc{xie2023pixiu,
      title={PIXIU: A Large Language Model, Instruction Data and Evaluation Benchmark for Finance}, 
      author={Qianqian Xie and Weiguang Han and Xiao Zhang and Yanzhao Lai and Min Peng and Alejandro Lopez-Lira and Jimin Huang},
      year={2023},
      eprint={2306.05443},
      archivePrefix={arXiv},
      primaryClass={cs.CL}
}
"""


class Classification(Task):
    CALCULATE_MCC = False
    LOWER_CASE = True
    VERSION = 1
    EVAL_LAST_TURN = True

    def reformulate_turn_req(self, req, turn_request, turn):
        return req

    def has_training_docs(self):
        return True

    def has_validation_docs(self):
        return True

    def has_test_docs(self):
        return True

    def training_docs(self):
        return self.dataset["train"]

    def validation_docs(self):
        return self.dataset["validation"]

    def test_docs(self):
        return self.dataset["test"]


    def construct_requests(self, doc, ctx):
        """Uses RequestFactory to construct Requests and returns an iterable of
        Requests which will be sent to the LM.

        :param doc:
            The document as returned from training_docs, validation_docs, or test_docs.
        :param ctx: str
            The context string, generated by fewshot_context. This includes the natural
            language description, as well as the few shot examples, and the question
            part of the document for `doc`.
        """
        cont_request = rf.greedy_until(ctx, {"until": "Text:"})
        return cont_request

    def doc_to_decontamination_query(self, doc):
         return doc["text"]

    def doc_to_text(self, doc):
        # TODO: Format the query prompt portion of the document example.
        return doc["query"]

    def doc_to_target(self, doc):
        # TODO: Format the query prompt portion of the document example.
        return doc["answer"]

    def process_results(self, doc, results):
        gold = doc["choices"][doc["gold"]]
        ini_result = results[0].strip()
        if self.LOWER_CASE:
            ini_result = ini_result.lower()

        for choice in doc["choices"]:
            ch = choice
            if self.LOWER_CASE:
                ch = ch.lower()
            if ch in ini_result:
                result = choice
                break
        else:
            choice = -1
            result = "missing"

        acc = 1.0 if gold == choice else 0.0

        results = {
            "acc": acc,
            "missing": int(result == "missing"),
            "f1": (result, gold),
            "macro_f1": (result, gold),
        }

        if self.CALCULATE_MCC:
            results["mcc"] = (choice, gold)

        return results


    def higher_is_better(self):
        metrics = {
            "acc": True,
            "f1": True,
            "macro_f1": True,
            "missing": False,
        }
        if self.CALCULATE_MCC:
            metrics["mcc"] = True
        return metrics

    def weighted_f1(cls, items):
        preds, golds = zip(*items)
        labels = list(set(golds))
        preds = np.array(preds)
        golds = np.array(golds)
        f1 = f1_score(preds, golds, average='weighted', labels=labels)
        return f1

    def macro_f1(cls, items):
        preds, golds = zip(*items)
        labels = list(set(golds))
        preds = np.array(preds)
        golds = np.array(golds)
        f1 = f1_score(preds, golds, average='macro', labels=labels)
        return f1

    def aggregation(self):
        metrics = {
            "acc": mean,
            "missing": mean,
            "f1": self.weighted_f1,
            "macro_f1": self.macro_f1,
        }
        if self.CALCULATE_MCC:
            metrics["mcc"] = matthews_corrcoef
        return metrics


class SequentialLabeling(Task):
    VERSION = 1
    DATASET_NAME = None
    LMAP = {'O': 0}
    EVAL_LAST_TURN = True

    def reformulate_turn_req(self, req, turn_request, turn):
        return req

    def has_training_docs(self):
        return False

    def has_validation_docs(self):
        return False

    def has_test_docs(self):
        return True

    def training_docs(self):
        return self.dataset["train"]

    def validation_docs(self):
        return self.dataset["validation"]

    def test_docs(self):
        return self.dataset["test"]

    def doc_to_text(self, doc):
        # TODO: Format the query prompt portion of the document example.
        return doc["query"]

    def doc_to_target(self, doc):
        return "\nAnswer: " + doc["answer"]

    def process_results(self, doc, results):
        return {
            "entity_f1": (doc["label"], results[0], doc["token"]),
            "f1": (doc["label"], results[0], doc["token"]),
        }

    def higher_is_better(self):
        return {
            "f1": True,
            "entity_f1": True,
        }

    def construct_requests(self, doc, ctx):
        """Uses RequestFactory to construct Requests and returns an iterable of
        Requests which will be sent to the LM.

        :param doc:
            The document as returned from training_docs, validation_docs, or test_docs.
        :param ctx: str
            The context string, generated by fewshot_context. This includes the natural
            language description, as well as the few shot examples, and the question
            part of the document for `doc`.
        """
        cont_request = rf.greedy_until(ctx, {"until": "Text:"})
        return cont_request

    def process_result(self, pred, gold, tokens):
        format_pred = ["O"] * len(gold)
        for index, pre in enumerate(pred.split("\n")[:len(tokens)]):
            try:
                word, label = pre.split(":")
            except:
                continue
            if word == tokens[index] and label in self.LMAP.keys():
                format_pred[index] = label
        return format_pred

    def entity_f1(self, items):
        golds, preds, tokens = zip(*items)

        list_preds = [self.process_result(pred, gold, token)
            for pred, gold, token in zip(preds, golds, tokens)]
        f1 = entity_score(list_preds, golds)
        return f1

    def process_label_result(self, pred, gold, tokens):
        format_pred = [-1] * len(gold)
        for index, pre in enumerate(pred.split("\n")[:len(tokens)]):
            try:
                word, label = pre.split(":")
            except:
                continue
            if word == tokens[index]:
                format_pred[index] = self.LMAP.get(label, -1)
        return format_pred

    def label_f1(self, items):
        golds, preds, tokens = zip(*items)

        list_preds = [self.process_label_result(pred, gold, token)
            for pred, gold, token in zip(preds, golds, tokens)]
        list_preds = [item for sublist in list_preds for item in sublist]
        golds = [self.LMAP[item] for sublist in golds for item in sublist]
        f1 = f1_score(list_preds, golds, average="weighted")
        return f1

    def aggregation(self):
        return {
            "entity_f1": self.entity_f1,
            "f1": self.label_f1,
        }


class AbstractiveSummarization(Task):
    VERSION = 1
    DATASET_NAME = None
    EVAL_LAST_TURN = True

    def reformulate_turn_req(self, req, turn_request, turn):
        return req

    def has_training_docs(self):
        return False

    def has_validation_docs(self):
        return False

    def has_test_docs(self):
        return True

    def training_docs(self):
        return self.dataset["train"]

    def validation_docs(self):
        return self.dataset["validation"]

    def test_docs(self):
        return self.dataset["test"]

    def doc_to_text(self, doc):
        # TODO: Format the query prompt portion of the document example.
        return doc["query"]

    def doc_to_target(self, doc):
        return doc["answer"]

    def process_results(self, doc, results):
        return {
            "rouge1": (doc["answer"], results[0]),
            "rouge2": (doc["answer"], results[0]),
            "rougeL": (doc["answer"], results[0]),
        }

    def higher_is_better(self):
        return {
            "rouge1": True,
            "rouge2": True,
            "rougeL": True,
        }

    def construct_requests(self, doc, ctx):
        """Uses RequestFactory to construct Requests and returns an iterable of
        Requests which will be sent to the LM.

        :param doc:
            The document as returned from training_docs, validation_docs, or test_docs.
        :param ctx: str
            The context string, generated by fewshot_context. This includes the natural
            language description, as well as the few shot examples, and the question
            part of the document for `doc`.
        """
        cont_request = rf.greedy_until(ctx, {"until": "Text:"})
        return cont_request

    def rouge_score(self, items):
        golds, preds = zip(*items)
        rouge = evaluate.load('rouge')
        results = rouge.compute(predictions=preds,
                                references=golds)
        return results

    def rouge1(self, items):
        results = self.rouge_score(items)
        return results['rouge1']

    def rouge2(self, items):
        results = self.rouge_score(items)
        return results['rouge2']

    def rougeL(self, items):
        results = self.rouge_score(items)
        return results['rougeL']

    def aggregation(self):
        return {
            "rouge1": self.rouge1,
            "rouge2": self.rouge2,
            "rougeL": self.rougeL,
        }


class ExtractiveSummarization(Task):
    VERSION = 1
    DATASET_NAME = None
    EVAL_LAST_TURN = True

    def reformulate_turn_req(self, req, turn_request, turn):
        return req

    def has_training_docs(self):
        return False

    def has_validation_docs(self):
        return False

    def has_test_docs(self):
        return True

    def training_docs(self):
        return self.dataset["train"]

    def validation_docs(self):
        return self.dataset["validation"]

    def test_docs(self):
        return self.dataset["test"]

    def doc_to_text(self, doc):
        # TODO: Format the query prompt portion of the document example.
        return doc["query"]

    def doc_to_target(self, doc):
        return doc["answer"]

    def process_results(self, doc, results):
        return {
            "rouge1": (doc["label"], doc["text"], results[0]),
            "rouge2": (doc["label"], doc["text"], results[0]),
            "rougeL": (doc["label"], doc["text"], results[0]),
        }

    def higher_is_better(self):
        return {
            "rouge1": True,
            "rouge2": True,
            "rougeL": True,
        }

    def construct_requests(self, doc, ctx):
        """Uses RequestFactory to construct Requests and returns an iterable of
        Requests which will be sent to the LM.

        :param doc:
            The document as returned from training_docs, validation_docs, or test_docs.
        :param ctx: str
            The context string, generated by fewshot_context. This includes the natural
            language description, as well as the few shot examples, and the question
            part of the document for `doc`.
        """
        cont_request = rf.greedy_until(ctx, {"until": "Text:"})
        return cont_request

    def get_sum(self, labels, texts):
        summ = []
        for label, text in zip(labels, texts):
            text = text.split("\n")
            new_text = "\n".join([text[index] for index in range(len(text)) if index < len(label) and label[index] == 1])
            summ.append(new_text)
        return summ

    def rouge_score(self, items):
        golds, texts, preds = zip(*items)
        golds = self.get_sum(golds, texts)
        preds = self.get_sum([val.split("\n") for val in preds], texts)
        rouge = evaluate.load('rouge')
        results = rouge.compute(predictions=preds,
                                references=golds)
        return results

    def rouge1(self, items):
        results = self.rouge_score(items)
        return results['rouge1']

    def rouge2(self, items):
        results = self.rouge_score(items)
        return results['rouge2']

    def rougeL(self, items):
        results = self.rouge_score(items)
        return results['rougeL']

    def aggregation(self):
        return {
            "rouge1": self.rouge1,
            "rouge2": self.rouge2,
            "rougeL": self.rougeL,
        }


class RelationExtraction(Task):
    VERSION = 1
    DATASET_NAME = None
    EVAL_LAST_TURN = True

    def reformulate_turn_req(self, req, turn_request, turn):
        return req

    def has_training_docs(self):
        return False

    def has_validation_docs(self):
        return False

    def has_test_docs(self):
        return True

    def training_docs(self):
        return self.dataset["train"]

    def validation_docs(self):
        return self.dataset["validation"]

    def test_docs(self):
        return self.dataset["test"]

    def doc_to_text(self, doc):
        # TODO: Format the query prompt portion of the document example.
        return doc["query"]

    def doc_to_target(self, doc):
        return doc["answer"]

    def process_results(self, doc, results):
        return {
            "precision": (doc["label"], results[0]),
            "recall": (doc["label"], results[0]),
            "f1": (doc["label"], results[0]),
        }

    def higher_is_better(self):
        return {
            "precision": True,
            "recall": True,
            "f1": True,
        }

    def construct_requests(self, doc, ctx):
        """Uses RequestFactory to construct Requests and returns an iterable of
        Requests which will be sent to the LM.

        :param doc:
            The document as returned from training_docs, validation_docs, or test_docs.
        :param ctx: str
            The context string, generated by fewshot_context. This includes the natural
            language description, as well as the few shot examples, and the question
            part of the document for `doc`.
        """
        cont_request = rf.greedy_until(ctx, {"until": "Text:"})
        return cont_request

    def process(self, items):
        golds, preds = zip(*items)

        all_golds = []
        all_preds = []

        for gold, pred in zip(golds, preds):
            all_golds.extend(gold)
            pred = pred.split("\n")
            all_preds.extend(pred)

        return set(all_golds), set(all_preds)

    def precision(self, items):
        golds, preds = self.process(items)
        tp = golds & preds
        prec = len(tp) / len(preds)
        return prec

    def recall(self, items):
        golds, preds = self.process(items)
        tp = golds & preds
        rec = len(tp) / len(golds)
        return rec

    def cal_f1(self, items):
        prec = self.precision(items)
        rec = self.recall(items)
        if prec + rec == 0.0:
            return 0.0
        return 2 * (prec * rec ) / (prec + rec)

    def aggregation(self):
        return {
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.cal_f1,
        }


class QA(Task):
    VERSION = 1
    DATASET_NAME = None
    EVAL_LAST_TURN = True

    def reformulate_turn_req(self, req, turn_request, turn):
        return req

    def has_training_docs(self):
        return True

    def has_validation_docs(self):
        return True

    def has_test_docs(self):
        return True

    def training_docs(self):
        return self.dataset["train"]

    def validation_docs(self):
        return self.dataset["validation"]

    def test_docs(self):
        return self.dataset["test"]

    def should_decontaminate(self):
         return True

    def doc_to_decontamination_query(self, doc):
         return doc["text"]

    def doc_to_text(self, doc):
        # TODO: Format the query prompt portion of the document example.
        return doc["query"]

    def construct_requests(self, doc, ctx):
        """Uses RequestFactory to construct Requests and returns an iterable of
        Requests which will be sent to the LM.

        :param doc:
            The document as returned from training_docs, validation_docs, or test_docs.
        :param ctx: str
            The context string, generated by fewshot_context. This includes the natural
            language description, as well as the few shot examples, and the question
            part of the document for `doc`.
        """
        cont_request = rf.greedy_until(ctx, {"until": "Text:"})
        return cont_request

    def doc_to_target(self, doc):
        return doc["answer"]

    def process_results(self, doc, results):
        gold = doc["answer"]

        acc = 1.0 if results[0].strip() == gold else 0.0

        return {
            "acc": acc,
        }

    def higher_is_better(self):
        return {
            "acc": True,
        }

    def aggregation(self):
        return {
            "acc": mean,
        }


class FPB(Classification):
    DATASET_PATH = "chancefocus/flare-fpb"


class FIQASA(Classification):
    DATASET_PATH = "chancefocus/flare-fiqasa"


class NER(Task):
    VERSION = 1
    DATASET_PATH = "chancefocus/flare-ner"
    DATASET_NAME = None

    def has_training_docs(self):
        return True

    def has_validation_docs(self):
        return True

    def has_test_docs(self):
        return True

    def training_docs(self):
        return self.dataset["train"]

    def validation_docs(self):
        return self.dataset["validation"]

    def test_docs(self):
        return self.dataset["test"]

    def should_decontaminate(self):
         return True

    def doc_to_decontamination_query(self, doc):
         return doc["text"]

    def doc_to_text(self, doc):
        # TODO: Format the query prompt portion of the document example.
        return doc["query"]

    def construct_requests(self, doc, ctx):
        """Uses RequestFactory to construct Requests and returns an iterable of
        Requests which will be sent to the LM.

        :param doc:
            The document as returned from training_docs, validation_docs, or test_docs.
        :param ctx: str
            The context string, generated by fewshot_context. This includes the natural
            language description, as well as the few shot examples, and the question
            part of the document for `doc`.
        """
        cont_request = rf.greedy_until(ctx, {"until": "Text:"})
        return cont_request

    def doc_to_target(self, doc):
        return doc["answer"]

    def process_results(self, doc, results):
        text = doc["text"]
        pred = process_text(results[0], text)

        return {
            "entity_f1": (pred, doc["label"], results[0])
        }

    def higher_is_better(self):
        return {
            "entity_f1": True,
        }

    @classmethod
    def entity_f1(cls, items):
        preds, golds, _ = zip(*items)
        f1 = entity_score(preds, golds)
        return f1

    def aggregation(self):
        return {
            "entity_f1": self.entity_f1,
        }


class FinQA(QA):
    DATASET_PATH = "chancefocus/flare-finqa"


class StockMovement(Classification):
    DATASET_NAME = None
    CALCULATE_MCC = True


class StockMovementBigData(StockMovement):
    DATASET_PATH = "chancefocus/flare-sm-bigdata"


class StockMovementACL(StockMovement):
    DATASET_PATH = "chancefocus/flare-sm-acl"


class StockMovementCIKM(StockMovement):
    DATASET_PATH = "chancefocus/flare-sm-cikm"


SM_TASKS = {
    "flare_sm_bigdata": StockMovementBigData,
    "flare_sm_acl": StockMovementACL,
    "flare_sm_cikm": StockMovementCIKM,
}


class Headlines(Classification):
    DATASET_PATH = "chancefocus/flare-headlines"

    def process_results(self, doc, results):
        gold = doc["gold"]

        return {
            "avg_f1": (doc["label_type"], int(results[0] != "Yes"), gold, results),
        }

    def higher_is_better(self):
        return {
            "avg_f1": True,
        }

    @classmethod
    def label_avg(cls, items):
        labels, preds, golds, rels = zip(*items)
        label_set = set(labels)
        labels = np.array(labels)
        preds = np.array(preds)
        golds = np.array(golds)
        all_f1s = []
        for l in label_set:
            pds = preds[labels == l]
            gds = golds[labels == l]
            f1 = f1_score(pds, gds, average='weighted', labels=[0, 1])
            all_f1s.append(f1)
        return np.mean(all_f1s)

    def construct_requests(self, doc, ctx):
        """Uses RequestFactory to construct Requests and returns an iterable of
        Requests which will be sent to the LM.

        :param doc:
            The document as returned from training_docs, validation_docs, or test_docs.
        :param ctx: str
            The context string, generated by fewshot_context. This includes the natural
            language description, as well as the few shot examples, and the question
            part of the document for `doc`.
        """
        cont_request = rf.greedy_until(ctx, {"until": "Text:"})
        return cont_request

    def aggregation(self):
        return {
            "avg_f1": self.label_avg,
        }


class FinerOrd(SequentialLabeling):
    DATASET_PATH = "chancefocus/flare-finer-ord"
    LMAP = {'O': 0, 'B-PER': 1, 'I-PER': 2, 'B-LOC': 3, 'I-LOC': 4, 'B-ORG': 5, 'I-ORG': 6}


class FOMC(Classification):
    DATASET_PATH = "chancefocus/flare-fomc"


class German(Classification):
    DATASET_PATH = "chancefocus/flare-german"


class Australian(Classification):
    DATASET_PATH = "chancefocus/flare-australian"

class TSA(Task):
     VERSION = 1
     DATASET_PATH = "chancefocus/flare-tsa"
     DATASET_NAME = None

     def has_training_docs(self):
         return False

     def has_validation_docs(self):
         return False

     def has_test_docs(self):
         return True

     def training_docs(self):
         return self.dataset["train"]

     def validation_docs(self):
         return self.dataset["validation"]

     def test_docs(self):
         return self.dataset["test"]

     def doc_to_text(self, doc):
         # TODO: Format the query prompt portion of the document example.
         return doc["query"]

     def doc_to_target(self, doc):
         return "\nAnswer: " + str(doc["answer"])

     def process_results(self, doc, results):
         pred = results[0].split("\n")[0]
         pred = re.findall(r'[0-9]+(?:\.[0-9]+)?', pred)
         missing = 0
         if not pred:
             pred = -100.0
             missing = 1
         else:
             pred = pred[0]
         pred = float(pred)
         return {
                 "rmse": (doc["answer"], pred),
                 "missing": missing
         }

     def higher_is_better(self):
         return {
             "rmse": False,
         }

     def construct_requests(self, doc, ctx):
         """Uses RequestFactory to construct Requests and returns an iterable of
         Requests which will be sent to the LM.

         :param doc:
             The document as returned from training_docs, validation_docs, or test_docs.
         :param ctx: str
             The context string, generated by fewshot_context. This includes the natural
             language description, as well as the few shot examples, and the question
             part of the document for `doc`.
         """
         cont_request = rf.greedy_until(ctx, {"until": "Answer:"})
         return cont_request

     def rmse(self, items):
         golds, preds = zip(*items)
         fgolds, fpreds = [], []
         for gold, pred in zip(golds, preds):
             if pred == -100.0:
                 continue
             fgolds.append(gold)
             fpreds.append(max(min(pred, 1.0), -1.0))
         rmse = mean_squared_error(fgolds, fpreds, squared=True)

         return rmse

     def aggregation(self):
         return {
             "rmse": self.rmse,
             "missing": mean,
         }



 class CFA(Classification):
     DATASET_PATH = "chancefocus/flare-cfa"
     LOWER_CASE = False


 class FINARGECCARC(Classification):
     DATASET_PATH = "chancefocus/flare-finarg-ecc-arc"


 class FINARGECCAUC(Classification):
     DATASET_PATH = "chancefocus/flare-finarg-ecc-auc"


 class MLESG(Classification):
     DATASET_PATH = "chancefocus/flare-mlesg"


 class FSRL(SequentialLabeling):
     DATASET_PATH = "chancefocus/flare-fsrl"
     LMAP = {key: index for index, key in enumerate(['O', 'I-QUANT', 'B-QUANT', 'I-TIME', 'B-TIME', 'I-MANNER', 'B-MANNER', 'I-THEME', 'B-THEME', 'I-VALUE', 'B-VALUE', 'I-WHOLE', 'B-WHOLE', 'I-LOCATION', 'B-LOCATION', 'I-AGENT', 'B-AGENT', 'I-CAUSE', 'B-CAUSE', 'I-SOURCE', 'B-SOURCE', 'I-REF_TIME', 'B-REF_TIME', 'I-CONDITION', 'B-CONDITION'])}

 class CFA(Classification):
     DATASET_PATH = "chancefocus/flare-cfa"

 class FinargECCAUC(Classification):
     DATASET_PATH = "chancefocus/flare-finarg-ecc-auc"

 class FinargECCARC(Classification):
     DATASET_PATH = "chancefocus/flare-finarg-ecc-arc"

 class CD(SequentialLabeling):
     DATASET_PATH = "chancefocus/flare-cd"
     LMAP = {key: index for index, key in enumerate(['O', 'I-CAUSE', 'B-CAUSE', 'I-EFFECT', 'B-EFFECT'])}

 class MultiFinEN(Classification):
     DATASET_PATH = "chancefocus/flare-multifin-en"

 class MA(Classification):
     DATASET_PATH = "chancefocus/flare-ma"

 class Causal20SC(Classification):
     DATASET_PATH = "chancefocus/flare-causal20-sc"

 class FNXL(SequentialLabeling):
     DATASET_PATH = "chancefocus/flare-fnxl"
     LMAP = {'B-BusinessCombinationContingentConsiderationArrangementsRangeOfOutcomesValueHigh': 140, 'B-VariableInterestEntityOwnershipPercentage': 646, 'B-GainLossOnDispositionOfAssets1': 119, 'B-IndefiniteLivedIntangibleAssetsExcludingGoodwill': 46, 'B-MarketingAndAdvertisingExpense': 269, 'B-ReportingUnitPercentageOfFairValueInExcessOfCarryingAmount': 142, 'B-CapitalizedComputerSoftwareNet': 91, 'B-BusinessCombinationConsiderationTransferredEquityInterestsIssuedAndIssuable': 183, 'B-LitigationSettlementExpense': 115, 'B-DefinedBenefitPlanExpectedAmortizationOfGainLossNextFiscalYear': 639, 'B-DeferredCompensationArrangementWithIndividualCompensationExpense': 15, 'B-ReclassificationFromAociCurrentPeriodTax': 152, 'B-OtherComprehensiveIncomeLossBeforeReclassificationsTax': 694, 'B-PreferredStockDividendsPerShareDeclared': 236, 'B-CapitalExpendituresIncurredButNotYetPaid': 344, 'B-DeferredCompensationArrangementWithIndividualContributionsByEmployer': 560, 'B-SeveranceCosts1': 311, 'B-InterestExpense': 784, 'B-SaleOfStockConsiderationReceivedOnTransaction': 76, 'B-LineOfCreditFacilityInterestRateAtPeriodEnd': 822, 'B-SharesIssuedPricePerShare': 137, 'B-EquityMethodInvestmentDifferenceBetweenCarryingAmountAndUnderlyingEquity': 63, 'B-EquitySecuritiesFvNi': 30, 'B-RightOfUseAssetObtainedInExchangeForOperatingLeaseLiability': 118, 'B-DefinedBenefitPlanFundedStatusOfPlan': 547, 'B-SharebasedCompensationArrangementBySharebasedPaymentAwardPurchasePriceOfCommonStockPercent': 323, 'B-TaxCutsAndJobsActOf2017IncomeTaxExpenseBenefit': 256, 'B-LongtermDebtWeightedAverageInterestRate': 364, 'B-ImpairmentOfIntangibleAssetsFinitelived': 71, 'B-ProceedsFromLinesOfCredit': 496, 'B-LongTermPurchaseCommitmentAmount': 701, 'B-DebtInstrumentFairValue': 335, 'B-RestructuringAndRelatedCostCostIncurredToDate1': 52, 'B-ShareBasedCompensationArrangementByShareBasedPaymentAwardEquityInstrumentsOtherThanOptionsVestedInPeriod': 581, 'B-FiniteLivedIntangibleAssetsAccumulatedAmortization': 143, 'B-StockRepurchasedAndRetiredDuringPeriodValue': 330, 'B-BusinessCombinationProFormaInformationRevenueOfAcquireeSinceAcquisitionDateActual': 77, 'B-ClassOfWarrantOrRightExercisePriceOfWarrantsOrRights1': 361, 'B-BusinessAcquisitionPurchasePriceAllocationGoodwillExpectedTaxDeductibleAmount': 550, 'B-OperatingLossCarryforwardsValuationAllowance': 173, 'B-BusinessAcquisitionEquityInterestsIssuedOrIssuableNumberOfSharesIssued': 32, 'B-DefinedContributionPlanMaximumAnnualContributionsPerEmployeePercent': 45, 'B-ContractWithCustomerLiabilityCurrent': 2, 'B-IncomeLossFromContinuingOperationsBeforeIncomeTaxesForeign': 474, 'B-FiniteLivedIntangibleAssetsAmortizationExpenseYearThree': 1306, 'B-DefinedBenefitPlanUltimateHealthCareCostTrendRate1': 62, 'B-DefinedBenefitPlanRecognizedNetGainLossDueToSettlements1': 317, 'B-UnrecognizedTaxBenefitsInterestOnIncomeTaxesExpense': 448, 'B-ForeignCurrencyTransactionGainLossRealized': 132, 'B-DeferredTaxAssetsOperatingLossCarryforwardsSubjectToExpiration': 262, 'B-RetainedEarningsAccumulatedDeficit': 174, 'B-ProceedsFromIssuanceOfCommonStock': 209, 'B-EmployeeServiceShareBasedCompensationAllocationOfRecognizedPeriodCostsCapitalizedAmount': 29, 'B-OtherComprehensiveIncomeLossPensionAndOtherPostretirementBenefitPlansTax': 284, 'B-InventoryWriteDown': 465, 'B-RestructuringReserve': 234, 'B-LitigationSettlementAmountAwardedToOtherParty': 42, 'B-DerivativeGainLossOnDerivativeNet': 87, 'B-SharebasedCompensationArrangementBySharebasedPaymentAwardEquityInstrumentsOtherThanOptionsAggregateIntrinsicValueVested': 241, 'B-DerivativeFixedInterestRate': 589, 'B-CashAndCashEquivalentsAtCarryingValue': 257, 'B-ContractWithCustomerAssetNet': 245, 'B-RestructuringAndRelatedCostExpectedCost1': 107, 'B-IncomeTaxHolidayAggregateDollarAmount': 347, 'B-OperatingLeaseCost': 248, 'B-AllowanceForDoubtfulAccountsReceivable': 146, 'B-RepaymentsOfDebt': 416, 'B-InterestPaid': 110, 'B-DeferredFinanceCostsNet': 28, 'B-IncomeTaxExaminationPenaltiesAndInterestAccrued': 271, 'B-ShareBasedCompensationArrangementByShareBasedPaymentAwardEquityInstrumentsOtherThanOptionsNonvestedNumber': 92, 'B-CapitalizedContractCostNet': 155, 'B-CumulativeEffectOfNewAccountingPrincipleInPeriodOfAdoption': 17, 'B-IncomeTaxesPaid': 495, 'B-EquityMethodInvestmentOtherThanTemporaryImpairment': 22, 'B-InterestPaidNet': 225, 'B-EquitySecuritiesWithoutReadilyDeterminableFairValueAmount': 175, 'B-ImpairmentOfLongLivedAssetsHeldForUse': 313, 'B-GoodwillAcquiredDuringPeriod': 156, 'B-DecreaseInUnrecognizedTaxBenefitsIsReasonablyPossible': 363, 'B-RestructuringAndRelatedCostIncurredCost': 75, 'B-StockRepurchasedDuringPeriodValue': 254, 'B-IncomeTaxExaminationPenaltiesAndInterestExpense': 525, 'B-ImpairmentOfIntangibleAssetsIndefinitelivedExcludingGoodwill': 55, 'B-PreferredStockLiquidationPreference': 157, 'B-ImpairmentOfIntangibleAssetsExcludingGoodwill': 158, 'B-IncomeTaxesPaidNet': 456, 'B-DefinedContributionPlanEmployerMatchingContributionPercent': 332, 'B-CostOfGoodsAndServicesSold': 274, 'B-DepreciationDepletionAndAmortization': 338, 'B-InterestExpenseDebt': 191, 'B-LineOfCreditFacilityUnusedCapacityCommitmentFeePercentage': 442, 'B-DisposalGroupIncludingDiscontinuedOperationConsideration': 6, 'B-UnrecognizedTaxBenefitsInterestOnIncomeTaxesAccrued': 14, 'B-SaleOfStockPricePerShare': 278, 'B-DefinedContributionPlanEmployerMatchingContributionPercentOfMatch': 267, 'B-FinitelivedIntangibleAssetsAcquired1': 202, 'B-PaymentsForRepurchaseOfCommonStock': 486, 'B-BusinessCombinationContingentConsiderationLiability': 103, 'B-RelatedPartyTransactionAmountsOfTransaction': 180, 'O': 0}

 class TATQA(QA):
     DATASET_PATH = "chancefocus/flare-tatqa"


 class FinRED(RelationExtraction):
     DATASET_PATH = "chancefocus/flare-finred"


class ECTSUM(ExtractiveSummarization):
    DATASET_PATH = "chancefocus/flare-ectsum"


class EDTSUM(AbstractiveSummarization):
    DATASET_PATH = "chancefocus/flare-edtsum"


class ConvFinQA(QA):
    DATASET_PATH = "chancefocus/flare-convfinqa"

    def reformulate_turn_req(self, req, turn_request, turn):
        if turn == 0:
            return req
        pre_answers = {
            f"answer{i}": turn_request[i][0]
            for i in range(turn)
        }
        if pre_answers:
            req.args = [req.args[0].format(**pre_answers)]
        return req
