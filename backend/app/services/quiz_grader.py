from decimal import Decimal, ROUND_HALF_UP
import re

from app.ai.quiz_generator import normalized


def percentage(earned, total):
    if not total:
        return 0.0
    return float((Decimal(earned) * 100 / Decimal(total)).quantize(Decimal(".01"), rounding=ROUND_HALF_UP))


def grade(kind, answer, key):
    if answer is None:
        return 0, ["Not answered"]
    if kind in ("mcq", "boolean"):
        correct = type(answer) is type(key["answer"]) and answer == key["answer"]
        return int(correct), ["Correct" if correct else "Incorrect"]

    # Award at most one mark per concept. Skip clauses with negation rather
    # than treating a literal keyword in a denial as a correct explanation.
    clauses = [normalized(clause) for clause in re.split(r"[.!?;\n]+", answer.replace("’", "'"))]
    positive = [f" {item} " for item in clauses if not re.search(r"\b(no|not|never|false|without|n t)\b", item)]
    earned = 0
    feedback = []
    for concept in key["concepts"]:
        matched = any(f" {normalized(phrase)} " in clause for phrase in concept["phrases"] for clause in positive)
        # Some terms legitimately contain “no”, e.g. “no preemption”. Remove
        # just the candidate term, then reject any other negation in that clause.
        if not matched:
            for phrase in concept["phrases"]:
                term = f" {normalized(phrase)} "
                if any(term in f" {clause} " and not re.search(r"\b(no|not|never|false|without|n t)\b",
                           f" {clause} ".replace(term, " ", 1)) for clause in clauses):
                    matched = True
                    break
        earned += int(matched)
        feedback.append(f"{concept['label']}: {'matched' if matched else 'not matched'}")
    return earned, feedback
