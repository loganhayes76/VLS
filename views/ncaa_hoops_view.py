import streamlit as st
import pandas as pd
from fetch_odds import get_ncaab_odds, get_vegas_spread, get_market_line
from hoops_stats import get_hoops_team_stats
from tracker_engine import log_explicit_to_system, batch_log_plays

def format_game_time(commence_time):
    return commence_time

def get_implied_prob(ml):
    if ml is None or ml == "N/A": return None
    if ml < 0: return abs(ml) / (abs(ml) + 100)
    else: return 100 / (ml + 100)
    
def format_ml(ml):
    if ml is None or ml == "N/A": return "N/A"
    return f"+{int(ml)}" if ml > 0 else str(int(ml))
    
def prob_to_american(prob):
    if prob <= 0 or prob >= 1: return "N/A"
    if prob > 0.5: return int(round((prob / (1 - prob)) * -100))
    else: return int(round(((1 - prob) / prob) * 100))

def render():
    st.header("🏀 Hardwood Upset Radar (NCAA)")
    h_tabs = st.tabs(["🎯 Live Matchups & Edges", "🔮 Bracket Simulator"])
    
    with h_tabs[0]:
        c1, c2 = st.columns(2)
        with c1:
            if st.button("🚀 Scan Hoops Slate", use_container_width=True):
                with st.spinner("Simulating Matchups..."):
                    b_games = get_ncaab_odds()
                    spread_res, ml_res, total_res = [], [], []
                    
                    if b_games:
                        for g in b_games:
                            h_t, a_t = g['home_team'], g['away_team']
                            
                            try:
                                h_s, d_e, d_t = get_hoops_team_stats(h_t)
                                a_s, _, _ = get_hoops_team_stats(a_t)
                            except:
                                continue 
                                
                            tempo = (h_s['tempo'] * a_s['tempo']) / d_t
                            h_p = (h_s['adj_o'] * a_s['adj_d'] / d_e / 100) * tempo
                            a_p = (a_s['adj_o'] * h_s['adj_d'] / d_e / 100) * tempo
                            
                            my_spread, my_total = round(a_p - h_p, 1), round(a_p + h_p, 1)
                            h_win_prob = (h_p**11.5) / (h_p**11.5 + a_p**11.5)
                            a_win_prob = 1.0 - h_win_prob
                            
                            v_s = get_vegas_spread(g, h_t, 'draftkings') or get_vegas_spread(g, h_t, 'betmgm')
                            v_t = get_market_line(g, 'totals', 'draftkings') or get_market_line(g, 'totals', 'betmgm')
                            
                            h_ml, a_ml = None, None
                            for book in g.get('bookmakers', []):
                                for m in book.get('markets', []):
                                    if m['key'] == 'h2h':
                                        for out in m.get('outcomes', []):
                                            if out['name'] == h_t and h_ml is None: h_ml = out.get('price')
                                            if out['name'] == a_t and a_ml is None: a_ml = out.get('price')
                                if h_ml is not None and a_ml is not None: break
                                
                            spread_edge = round((v_s if v_s else 0) - my_spread, 1) if v_s else 0.0
                            s_stars = "⭐⭐⭐⭐" if abs(spread_edge) >= 2.5 else "⭐⭐"
                            
                            spread_res.append({
                                "Time": format_game_time(g.get('commence_time', '')),
                                "Matchup": f"{a_t} @ {h_t}", 
                                "Model Spread": f"{h_t} {my_spread if my_spread <= 0 else f'+{my_spread}'}", 
                                "Vegas Spread": f"{h_t} {v_s if v_s <= 0 else f'+{v_s}'}" if v_s is not None else "N/A", 
                                "Edge": spread_edge, "Stars": s_stars
                            })
                            
                            total_edge = round(my_total - v_t, 1) if v_t else 0.0
                            t_stars = "⭐⭐⭐⭐" if abs(total_edge) >= 4.0 else "⭐⭐"
                            
                            total_res.append({
                                "Time": format_game_time(g.get('commence_time', '')),
                                "Matchup": f"{a_t} @ {h_t}", 
                                "Model Total": my_total, 
                                "Vegas Total": v_t if v_t else "N/A", 
                                "Edge": total_edge, "Stars": t_stars
                            })
                            
                            my_home_ml = prob_to_american(h_win_prob)
                            my_away_ml = prob_to_american(a_win_prob)
                            vegas_home_prob = get_implied_prob(h_ml)
                            
                            if vegas_home_prob is not None:
                                ml_edge_val = round((h_win_prob - vegas_home_prob) * 100, 1)
                                ml_stars = "⭐⭐⭐⭐" if abs(ml_edge_val) >= 4.0 else "⭐⭐"
                            else:
                                ml_edge_val = 0.0; ml_stars = "N/A"
                                
                            ml_res.append({
                                "Time": format_game_time(g.get('commence_time', '')),
                                "Matchup": f"{a_t} @ {h_t}", 
                                "Model Home ML": f"{h_t} {format_ml(my_home_ml)}",
                                "Vegas Home ML": f"{h_t} {format_ml(h_ml)}" if h_ml is not None else "N/A", 
                                "Model Away ML": f"{a_t} {format_ml(my_away_ml)}",
                                "Vegas Away ML": f"{a_t} {format_ml(a_ml)}" if a_ml is not None else "N/A", 
                                "Model Win %": f"{round(h_win_prob * 100, 1)}%",
                                "Vegas Win %": f"{round(vegas_home_prob * 100, 1)}%" if vegas_home_prob is not None else "N/A",
                                "Edge (%)": ml_edge_val, "Stars": ml_stars
                            })
                            
                        st.session_state.ncaab_spread_board = spread_res
                        st.session_state.ncaab_total_board = total_res
                        st.session_state.ncaab_ml_board = ml_res

        with c2:
            if st.button("💾 Log Hoops Plays", use_container_width=True): 
                log_explicit_to_system("NCAA BB", st.session_state.get('ncaab_spread_board', []), "Spread", "Model Spread", "Vegas Spread", "Edge", "Stars")
            
            if st.button("🌟 Auto-Log 5-Star Hoops Plays", use_container_width=True):
                five_stars = []
                for brd, mkt, p, v in [('ncaab_spread_board', 'Spread', 'Model Spread', 'Vegas Spread'), ('ncaab_total_board', 'Total', 'Model Total', 'Vegas Total')]:
                    if brd in st.session_state:
                        for g in st.session_state[brd]:
                            if g.get('Stars') == '⭐⭐⭐⭐⭐': 
                                five_stars.append({"Sport":"🏀 NCAA Hoops", "Matchup":g['Matchup'], "Market":mkt, "Proj":g[p], "Vegas":g[v], "Edge":g['Edge'], "Stars":'⭐⭐⭐⭐⭐'})
                if five_stars: batch_log_plays(five_stars)
                else: st.warning("No 5-Star Hoops plays generated yet.")

        team_sub_tabs = st.tabs(["+/- Spreads", "💰 Moneylines", "📈 Totals"])
        
        with team_sub_tabs[0]:
            if 'ncaab_spread_board' in st.session_state and st.session_state.ncaab_spread_board:
                st.dataframe(pd.DataFrame(st.session_state.ncaab_spread_board).sort_values(by="Edge", key=abs, ascending=False), use_container_width=True)
        
        with team_sub_tabs[1]:
            if 'ncaab_ml_board' in st.session_state and st.session_state.ncaab_ml_board:
                st.dataframe(pd.DataFrame(st.session_state.ncaab_ml_board).sort_values(by="Edge (%)", key=abs, ascending=False), use_container_width=True)
                
        with team_sub_tabs[2]:
            if 'ncaab_total_board' in st.session_state and st.session_state.ncaab_total_board:
                st.dataframe(pd.DataFrame(st.session_state.ncaab_total_board).sort_values(by="Edge", key=abs, ascending=False), use_container_width=True)
            
    with h_tabs[1]:
        BRACKET_REGIONS = {
            "East": ["Duke", "Siena", "Ohio St.", "TCU", "St. John's", "Northern Iowa", "Kansas", "California Baptist", "Louisville", "South Florida", "Michigan St.", "North Dakota St.", "UCLA", "UCF", "UConn", "Furman"],
            "South": ["Florida", "Prairie View A&M", "Clemson", "Iowa", "Vanderbilt", "McNeese", "Nebraska", "Troy", "North Carolina", "VCU", "Illinois", "Penn", "Saint Mary's", "Texas A&M", "Houston", "Idaho"],
            "West": ["Arizona", "LIU", "Villanova", "Utah St.", "Wisconsin", "High Point", "Arkansas", "Hawaii", "BYU", "Texas", "Gonzaga", "Kennesaw St.", "Miami FL", "Missouri", "Purdue", "Queens"],
            "Midwest": ["Michigan", "Howard", "Georgia", "Saint Louis", "Texas Tech", "Akron", "Alabama", "Hofstra", "Tennessee", "SMU", "Virginia", "Wright St.", "Kentucky", "Santa Clara", "Iowa St.", "Tennessee St."]
        }
        all_tourney_teams = sorted([team for region in BRACKET_REGIONS.values() for team in region])
        
        def sim_matchup(t1, t2):
            s1, de, dt = get_hoops_team_stats(t1); s2, _, _ = get_hoops_team_stats(t2)
            tempo = (s1['tempo'] * s2['tempo']) / dt
            p1, p2 = (s1['adj_o'] * s2['adj_d'] / de / 100) * tempo, (s2['adj_o'] * s1['adj_d'] / de / 100) * tempo
            p1_win_prob = (p1**11.5) / (p1**11.5 + p2**11.5)
            if p1_win_prob >= 0.5: return t1, p1_win_prob, p1, p2
            else: return t2, (1.0 - p1_win_prob), p1, p2

        sim_tabs = st.tabs(["🔬 Target Matchup Sandbox", "🔮 64-Team Auto-Solver"])
        
        with sim_tabs[0]:
            st.subheader("🔬 Target Matchup Sandbox")
            st.caption("Select any two teams to deep dive a potential matchup.")
            w_c1, w_c2 = st.columns(2)
            with w_c1: team1 = st.selectbox("Team 1 (Away)", all_tourney_teams, index=all_tourney_teams.index('Duke') if 'Duke' in all_tourney_teams else 0)
            with w_c2: team2 = st.selectbox("Team 2 (Home/Neutral)", all_tourney_teams, index=all_tourney_teams.index('North Carolina') if 'North Carolina' in all_tourney_teams else 1)
            
            if st.button("🔬 Execute Deep Dive Simulation"):
                if team1 == team2: st.error("⚠️ Please select two different teams.")
                else:
                    with st.spinner(f"Simulating {team1} vs {team2}..."):
                        winner, prob, p1_score, p2_score = sim_matchup(team1, team2)
                        s1, de, dt = get_hoops_team_stats(team1); s2, _, _ = get_hoops_team_stats(team2)
                        proj_tempo = (s1['tempo'] * s2['tempo']) / dt
                        t1_win_prob = prob if winner == team1 else 1.0 - prob
                        t2_win_prob = prob if winner == team2 else 1.0 - prob
                        my_spread = p1_score - p2_score 
                        spread_str = f"{team2} {round(my_spread, 1) if my_spread <= 0 else f'+{round(my_spread, 1)}'}"
                        
                        st.divider()
                        st.markdown(f"<h3 style='text-align: center;'>🏆 Projected Winner: {winner} ({round(prob*100, 1)}%)</h3>", unsafe_allow_html=True)
                        st.markdown(f"<h4 style='text-align: center;'>Score: {team1} {round(p1_score, 1)} - {team2} {round(p2_score, 1)}</h4>", unsafe_allow_html=True)
                        st.divider()
                        
                        c1, c2, c3 = st.columns(3)
                        with c1:
                            st.info(f"**✈️ {team1}**")
                            st.metric("Win Probability", f"{round(t1_win_prob*100, 1)}%")
                            st.metric("Adj. Offense", round(s1['adj_o'], 1)); st.metric("Adj. Defense", round(s1['adj_d'], 1))
                        with c2:
                            st.warning("**⚖️ Game Environment**")
                            st.metric("Projected Spread", spread_str); st.metric("Projected Total", round(p1_score + p2_score, 1))
                            st.metric("Projected Pace", round(proj_tempo, 1))
                        with c3:
                            st.error(f"**🏠 {team2}**")
                            st.metric("Win Probability", f"{round(t2_win_prob*100, 1)}%")
                            st.metric("Adj. Offense", round(s2['adj_o'], 1)); st.metric("Adj. Defense", round(s2['adj_d'], 1))

        with sim_tabs[1]:
            st.subheader("🔮 Full 64-Team Bracket Auto-Solver")
            if st.button("🧬 Execute Full Simulation"):
                with st.spinner("Crunching all 63 matchups..."):
                    all_regions_results = {}; final_four_teams = []
                    for region_name, teams in BRACKET_REGIONS.items():
                        current_round = teams; region_history = []
                        for round_num in [64, 32, 16, 8]:
                            next_round = []; round_results = []
                            for i in range(0, len(current_round), 2):
                                t1, t2 = current_round[i], current_round[i+1]
                                winner, prob, s1, s2 = sim_matchup(t1, t2)
                                next_round.append(winner)
                                loser = t2 if winner == t1 else t1
                                round_results.append(f"**{winner}** def. {loser} *(Prob: {round(prob*100, 1)}%)*")
                            region_history.append((round_num, round_results)); current_round = next_round
                        all_regions_results[region_name] = region_history
                        final_four_teams.append(current_round[0])
                    
                    ff_w1, ff_p1, _, _ = sim_matchup(final_four_teams[0], final_four_teams[1]) 
                    ff_w2, ff_p2, _, _ = sim_matchup(final_four_teams[2], final_four_teams[3]) 
                    champ, champ_p, c_s1, c_s2 = sim_matchup(ff_w1, ff_w2)
                    
                    st.success(f"🏆 National Champion: {champ} ({round(champ_p*100,1)}% over {ff_w1 if champ==ff_w2 else ff_w2})")
                    st.divider(); st.subheader("🏟️ The Final Four")
                    c1, c2, c3 = st.columns(3)
                    with c1: st.info(f"**Left Side**\n\n{final_four_teams[0]}\nvs\n{final_four_teams[1]}"); st.write(f"👉 **{ff_w1}** advances")
                    with c2: st.error(f"**🏆 Championship**\n\n{ff_w1} vs {ff_w2}\n\n**Proj Score:** {round(c_s1,1)} - {round(c_s2,1)}")
                    with c3: st.info(f"**Right Side**\n\n{final_four_teams[2]}\nvs\n{final_four_teams[3]}"); st.write(f"👉 **{ff_w2}** advances")
