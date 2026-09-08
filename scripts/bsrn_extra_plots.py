"""Supplementary figures from the original BSRN QC workflow."""
from pathlib import Path


def generate_extra_plots(dat_path, qc_root, parsed_data):
    import copy
    import matplotlib.pyplot as plt
    from bsrn_swd_sumsw_time_of_day import create_plots
    from scripts.bsrn_qc_continue import extract_optional_logical_records

    frame, metadata = parsed_data
    folder = Path(qc_root) / (dat_path.stem + '_plots')
    folder.mkdir(parents=True, exist_ok=True)
    plots, warnings = [], []
    try:
        result = create_plots(dat_path, output_dir=folder,
                              parsed_data=(frame.copy(deep=True), copy.deepcopy(metadata)))
        for key, title in [('daily_panel_grid', 'SWD / SumSW · daily panels'),
                           ('all_days_overlay', 'SWD / SumSW · all days')]:
            plots.append({'path': Path(result[key]), 'title': title})
    except Exception as exc:
        warnings.append(f'Time-of-day plots: {exc}')
    try:
        records = extract_optional_logical_records(dat_path, metadata['year'], metadata['month'],
                    metadata['station_code'], metadata['latitude'], metadata['longitude'])
        for record, rows in records.items():
            path = folder / f'{dat_path.stem}_{record}.png'
            try:
                plot_logical_record(record, rows, path, plt)
                plots.append({'path': path, 'title': record + ' · additional measurements'})
            except Exception as exc:
                warnings.append(f'{record} plot: {exc}')
    except Exception as exc:
        warnings.append(f'Optional logical-record plots: {exc}')
    finally:
        plt.close('all')
    return plots, warnings

import datetime as dt

def plot_logical_record(record_name: str, rows: list[dict[str, object]], output_path: Path, plt) -> None:
    time_values = [row.get("Date/Time") for row in rows]
    has_time = bool(time_values and all(time_values))
    plot_excluded = {
        "Station",
        "Date/Time",
        "Latitude",
        "Longitude",
        "SYNOP format",
        "date_day",
        "time_min",
        "line",
        "FM 12-XII Ext. SYNOP code",
    }
    numeric_cols = [
        key
        for key in rows[0].keys()
        if key not in plot_excluded and any(isinstance(row.get(key), (int, float)) for row in rows)
    ]
    primary_cols = [col for col in numeric_cols if "standard deviation" not in col and "minimum" not in col and "maximum" not in col]

    if has_time and primary_cols:
        fig_height = max(4.0, min(2.0 * len(primary_cols), 18.0))
        fig, axes = plt.subplots(len(primary_cols), 1, figsize=(12, fig_height), sharex=True)
        if len(primary_cols) == 1:
            axes = [axes]
        x_values = [dt.datetime.fromisoformat(str(value)) for value in time_values]
        for ax, col in zip(axes, primary_cols):
            y_values = [row.get(col) for row in rows]
            ax.plot(x_values, y_values, linewidth=0.9, color="#2563eb")
            ax.set_ylabel(short_label(col), rotation=0, ha="right", va="center", labelpad=58)
            ax.grid(True, alpha=0.25)
        axes[-1].set_xlabel("Date/Time")
        axes[0].set_title(f"{record_name} optional logical record")
        fig.autofmt_xdate()
        fig.tight_layout()
        fig.savefig(output_path, dpi=150)
        plt.close(fig)
        return

    fig, ax = plt.subplots(figsize=(12, 5))
    if has_time and primary_cols:
        x_values = [dt.datetime.fromisoformat(str(value)) for value in time_values]
        for col in primary_cols[:8]:
            y_values = [row.get(col) for row in rows]
            ax.plot(x_values, y_values, linewidth=1.0, label=short_label(col))
        ax.set_xlabel("Date/Time")
        ax.set_ylabel("Value")
        ax.legend(loc="best", fontsize="small")
        fig.autofmt_xdate()
    elif numeric_cols:
        for col in numeric_cols[:8]:
            y_values = [row.get(col) for row in rows]
            ax.plot(range(1, len(rows) + 1), y_values, linewidth=1.0, label=short_label(col))
        ax.set_xlabel("Row")
        ax.set_ylabel("Value")
        ax.legend(loc="best", fontsize="small")
    else:
        ax.axis("off")
        sample = "\n".join(str(row.get("FM 12-XII Ext. SYNOP code", ""))[:100] for row in rows[:12])
        ax.text(0.01, 0.98, f"{len(rows)} SYNOP record(s)\n\n{sample}", va="top", ha="left", family="monospace")

    ax.set_title(f"{record_name} optional logical record")
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)

def short_label(label: str) -> str:
    return label.split("[", 1)[0].strip().replace(" radiation", "")
