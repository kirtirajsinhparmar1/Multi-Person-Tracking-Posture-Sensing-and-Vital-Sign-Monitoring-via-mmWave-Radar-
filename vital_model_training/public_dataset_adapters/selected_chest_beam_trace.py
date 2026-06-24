from vital_model_training.features import read_trace, valid_locked_row


def read_valid_selected_chest_beam_rows(path):
    return [row for row in read_trace(path) if valid_locked_row(row)]
