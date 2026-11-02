"""Start-up seeding for wave 3 WS-L (idempotent): the "Agentic AI" question set (F14), the SOC 2 starter controls and the
platform's own AI systems in Futran's organization (F19). A failure is logged and never stops the platform starting."""
import logging

log = logging.getLogger(__name__)


def on_start(app) -> None:
    from app.platformtrust.seed import seed_controls, seed_platform_ai
    from app.questionnaire.agentic import ensure_agentic_questions

    db = app.state.sessionmaker()
    try:
        out = {"agentic_questions": ensure_agentic_questions(db), "soc_controls": seed_controls(db), "platform_ai": seed_platform_ai(db, app.state.settings)}
        db.commit()
        if any(out.values()):
            log.info("Wave 3 WS-L start-up seed: %s", out)
    except Exception as exc:  # an unmigrated or locked database: start anyway
        db.rollback()
        log.warning("Wave 3 WS-L start-up seed did not run: %s", exc)
    finally:
        db.close()
