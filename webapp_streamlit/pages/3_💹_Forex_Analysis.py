#!/usr/bin/env python3
"""
Facebook Post Monitor - Advanced Forex Chart Engine
💹 Phase 1 Complete - Professional Forex-style Trading Interface
Advanced Chart Controls, Export Features, Custom Zoom & Date Range Selection
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
import logging
import base64
import io
import json
import sys
import os

# Add parent directory to Python path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

try:
    # Import database reader
    from webapp_streamlit.core.db_reader import (
        get_forex_data,
        get_source_urls,
        get_system_overview
    )
except ImportError:
    # Fallback for development/deployment scenarios
    def get_forex_data(timeframe='1H', source_url=None, limit=500, date_range=None):
        return pd.DataFrame()
    
    def get_source_urls():
        return []
    
    def get_system_overview():
        return {}

# Configure page
st.set_page_config(
    page_title="Forex Analysis",
    page_icon="💹",
    layout="wide"
)

def format_number(num):
    """Format large numbers for display"""
    if num >= 1_000_000:
        return f"{num/1_000_000:.1f}M"
    elif num >= 1_000:
        return f"{num/1_000:.1f}K"
    else:
        return str(num)

# Advanced Chart Controls & Export Functions

def export_chart_data(df: pd.DataFrame, chart_type: str = "forex") -> str:
    """Export chart data as downloadable file"""
    if df.empty:
        return None
    
    # Create export data
    export_data = {
        "export_info": {
            "chart_type": chart_type,
            "timestamp": datetime.now().isoformat(),
            "total_candles": len(df),
            "timeframe": st.session_state.get('selected_timeframe', '1H')
        },
        "ohlc_data": df.to_dict('records')
    }
    
    # Convert to JSON
    json_str = json.dumps(export_data, indent=2, default=str)
    
    # Encode to base64 for download
    b64 = base64.b64encode(json_str.encode()).decode()
    href = f'data:application/json;base64,{b64}'
    
    return href

def create_chart_config(advanced_controls: bool = True) -> dict:
    """Create enhanced chart configuration"""
    base_config = {
        'displayModeBar': True,
        'displaylogo': False,
        'modeBarButtonsToRemove': [],
        'toImageButtonOptions': {
            'format': 'png',
            'filename': f'forex_chart_{datetime.now().strftime("%Y%m%d_%H%M%S")}',
            'height': 800,
            'width': 1200,
            'scale': 1
        }
    }
    
    if advanced_controls:
        # Enable all advanced controls
        base_config['modeBarButtonsToAdd'] = [
            'drawline', 'drawopenpath', 'drawclosedpath', 
            'drawcircle', 'drawrect', 'eraseshape'
        ]
        # Keep zoom and pan
        base_config['modeBarButtonsToRemove'] = ['lasso2d']
    else:
        # Remove some controls for simple mode
        base_config['modeBarButtonsToRemove'] = ['pan2d', 'lasso2d']
    
    return base_config

@st.cache_data(ttl=180)  # Cache for 3 minutes
def load_forex_data(timeframe: str = '1H', source_url=None, limit: int = 500, date_range=None):
    """Load forex data with caching and date filtering"""
    data = get_forex_data(
        timeframe=timeframe, source_url=source_url, limit=limit
    )
    
    # Apply date range filter if specified
    if not data.empty and date_range:
        start_date, end_date = date_range
        if 'timestamp' in data.columns:
            data['timestamp'] = pd.to_datetime(data['timestamp'])
            mask = (data['timestamp'] >= start_date) & (data['timestamp'] <= end_date)
            data = data[mask]
    
    return data

@st.cache_data(ttl=300)
def load_source_urls():
    """Load source URLs with caching"""
    return get_source_urls()

def create_advanced_forex_chart(
    df: pd.DataFrame, 
    title: str = "💹 Advanced Forex Chart",
    chart_type: str = "candlestick",
    show_volume: bool = True,
    custom_config: dict = None
) -> go.Figure:
    """
    Tạo biểu đồ forex nâng cao với multiple chart types và advanced features
    
    Args:
        df: DataFrame với OHLC data
        title: Tiêu đề biểu đồ
        chart_type: Loại chart ('candlestick', 'line', 'ohlc', 'area')
        show_volume: Hiển thị volume subplot
        custom_config: Custom configuration options
        
    Returns:
        Plotly Figure với advanced forex chart
    """
    if df.empty:
        fig = go.Figure()
        fig.add_annotation(
            text="🚫 Không có dữ liệu",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=20, color="gray")
        )
        fig.update_layout(height=500, template="plotly_dark")
        return fig
    
    # Create subplots based on volume setting
    if show_volume and 'volume' in df.columns:
        from plotly.subplots import make_subplots
        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.05,
            subplot_titles=('Price Chart', 'Volume'),
            row_heights=[0.7, 0.3]
        )
        main_row = 1
        volume_row = 2
    else:
        fig = go.Figure()
        main_row = None
        volume_row = None
    
    # === MAIN PRICE CHART ===
    if chart_type == "candlestick":
        price_trace = go.Candlestick(
            x=df['timestamp'],
            open=df['open'],
            high=df['high'],
            low=df['low'], 
            close=df['close'],
            name="OHLC",
            increasing_line_color='#26a69a',
            decreasing_line_color='#ef5350',
            increasing_fillcolor='rgba(38, 166, 154, 0.3)',
            decreasing_fillcolor='rgba(239, 83, 80, 0.3)'
        )
    elif chart_type == "line":
        price_trace = go.Scatter(
            x=df['timestamp'],
            y=df['close'],
            mode='lines',
            name="Close Price",
            line=dict(color='#26a69a', width=2),
            fill='tonexty'
        )
    elif chart_type == "ohlc":
        price_trace = go.Ohlc(
            x=df['timestamp'],
            open=df['open'],
            high=df['high'],
            low=df['low'],
            close=df['close'],
            name="OHLC",
            increasing_line_color='#26a69a',
            decreasing_line_color='#ef5350'
        )
    elif chart_type == "area":
        price_trace = go.Scatter(
            x=df['timestamp'],
            y=df['close'],
            mode='lines',
            fill='tozeroy',
            name="Close Price",
            line=dict(color='#26a69a', width=2),
            fillcolor='rgba(38, 166, 154, 0.2)'
        )
    
    # Add price trace
    if main_row:
        fig.add_trace(price_trace, row=main_row, col=1)
    else:
        fig.add_trace(price_trace)
    
    # === VOLUME CHART ===
    if show_volume and 'volume' in df.columns and volume_row:
        # Color volume bars based on price movement
        volume_colors = []
        for i in range(len(df)):
            if df.iloc[i]['close'] >= df.iloc[i]['open']:
                volume_colors.append('#26a69a')
            else:
                volume_colors.append('#ef5350')
        
        volume_trace = go.Bar(
            x=df['timestamp'],
            y=df['volume'],
            name="Volume",
            marker_color=volume_colors,
            opacity=0.7
        )
        
        fig.add_trace(volume_trace, row=volume_row, col=1)
    
    # === ADVANCED STYLING ===
    fig.update_layout(
        title=dict(
            text=title,
            font=dict(size=20, color='white'),
            x=0.5
        ),
        template="plotly_dark",
        height=700 if show_volume else 600,
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            bgcolor='rgba(0,0,0,0.5)'
        ),
        font=dict(size=12, color='white'),
        plot_bgcolor='rgba(17, 17, 17, 1)',
        paper_bgcolor='rgba(17, 17, 17, 1)',
        margin=dict(l=60, r=60, t=100, b=60),
        hovermode='x unified'
    )
    
    # Advanced grid styling
    fig.update_xaxes(
        title_text="Time",
        showgrid=True,
        gridwidth=1,
        gridcolor='rgba(128,128,128,0.2)',
        showline=True,
        linewidth=1,
        linecolor='rgba(128,128,128,0.3)',
        color='white'
    )
    
    fig.update_yaxes(
        title_text="Price", 
        showgrid=True,
        gridwidth=1,
        gridcolor='rgba(128,128,128,0.2)',
        showline=True,
        linewidth=1, 
        linecolor='rgba(128,128,128,0.3)',
        color='white'
    )
    
    # Volume y-axis styling
    if show_volume and volume_row:
        fig.update_yaxes(
            title_text="Volume",
            showgrid=True,
            gridcolor='rgba(128,128,128,0.1)',
            row=volume_row, col=1
        )
    
    # Disable range slider for cleaner look
    fig.update_layout(xaxis_rangeslider_visible=False)
    
    # Apply custom configuration if provided
    if custom_config:
        fig.update_layout(**custom_config)
    
    return fig


def main():
    """Advanced Forex Chart Dashboard - Phase 1 Complete with Advanced Controls"""
    
    # === HEADER ===
    st.title("💹 Advanced Forex Chart Engine")
    st.markdown("**Phase 1 Complete** - Professional Trading Interface với Advanced Chart Controls")
    
    # === ADVANCED CHART CONTROLS ===
    with st.expander("⚙️ Advanced Chart Controls", expanded=True):
        ctrl_col1, ctrl_col2, ctrl_col3, ctrl_col4, ctrl_col5 = st.columns([1, 1, 1, 1, 1])
        
        with ctrl_col1:
            chart_type = st.selectbox(
                "📊 Chart Type",
                options=['candlestick', 'line', 'ohlc', 'area'],
                index=0,
                format_func=lambda x: {
                    'candlestick': '🕯️ Candlestick',
                    'line': '📈 Line Chart',
                    'ohlc': '📊 OHLC Bars',
                    'area': '🏔️ Area Chart'
                }[x]
            )
        
        with ctrl_col2:
            timeframe = st.selectbox(
                "⏰ Timeframe",
                options=['5T', '15T', '30T', '1H', '2H', '4H', '8H', '1D'],
                index=3,
                help="5T=5min, 15T=15min, 30T=30min, 1H=1hour, 2H=2hours, 4H=4hours, 8H=8hours, 1D=1day"
            )
            
            # Store in session state for export
            st.session_state.selected_timeframe = timeframe
        
        with ctrl_col3:
            show_volume = st.checkbox("📊 Show Volume", value=True)
            advanced_controls = st.checkbox("🎛️ Advanced Controls", value=True)
        
        with ctrl_col4:
            # Date range picker for custom zoom
            use_custom_range = st.checkbox("📅 Custom Date Range")
            if use_custom_range:
                start_date = st.date_input("Start Date", value=datetime.now() - timedelta(days=7))
                end_date = st.date_input("End Date", value=datetime.now())
                custom_date_range = (start_date, end_date)
            else:
                custom_date_range = None
        
        with ctrl_col5:
            data_limit = st.slider("📈 Data Points", 50, 1000, 500, 50)
    
    # === BASIC CONTROLS ===
    basic_col1, basic_col2, basic_col3, basic_col4 = st.columns([1, 2, 1, 2])
    
    with basic_col1:
        if st.button("🔄 Refresh Data"):
            st.cache_data.clear()
            st.rerun()
    
    with basic_col2:
        # Market selector
        source_urls = load_source_urls()
        market_options = ["🌐 All Markets"] + [f"📊 {url.split('/')[-1][:20]}" for url in source_urls]
        selected_market = st.selectbox("📈 Market Selection", market_options)
        
        selected_source = None if selected_market.startswith("🌐") else source_urls[market_options.index(selected_market) - 1]
    
    with basic_col3:
        if st.button("💾 Export Chart"):
            st.session_state.show_export = True
    
    with basic_col4:
        st.markdown(f"*Last Update: {datetime.now().strftime('%H:%M:%S')} | Mode: Advanced Controls {'✅' if advanced_controls else '❌'}*")
    
    st.divider()
    
    # === ADVANCED FOREX CHART ===
    try:
        # Load data with advanced parameters
        forex_data = load_forex_data(
            timeframe=timeframe,
            source_url=selected_source,
            limit=data_limit,
            date_range=custom_date_range
        )
        
        if forex_data.empty:
            st.warning("⚠️ Không có dữ liệu cho cấu hình đã chọn")
            st.info("""
            **Thử các cách sau:**
            - Chọn timeframe khác (1H thay vì 5T)
            - Chọn "All Markets" thay vì market cụ thể
            - Tăng số lượng data points
            - Bỏ custom date range nếu đang sử dụng
            """)
        else:
            # Market info với advanced details
            market_name = "All Markets" if selected_source is None else selected_source.split('/')[-1]
            chart_title = f"💹 {market_name} | {timeframe} | {chart_type.upper()} | {len(forex_data)} candles"
            
            if custom_date_range:
                chart_title += f" | Custom Range: {custom_date_range[0]} to {custom_date_range[1]}"
            
            # === ENHANCED PRICE STATS ===
            if len(forex_data) >= 1:
                latest = forex_data.iloc[-1]
                prev_close = forex_data.iloc[-2]['close'] if len(forex_data) >= 2 else latest['close']
                change = latest['close'] - prev_close
                change_pct = (change / prev_close * 100) if prev_close != 0 else 0
                
                # Enhanced metrics with more data
                metric_col1, metric_col2, metric_col3, metric_col4, metric_col5, metric_col6 = st.columns(6)
                
                with metric_col1:
                    delta_color = "normal" if change >= 0 else "inverse"
                    st.metric("💰 Current", f"{latest['close']:.1f}", f"{change:+.1f}", delta_color=delta_color)
                
                with metric_col2:
                    st.metric("📈 High", f"{latest['high']:.1f}")
                
                with metric_col3:
                    st.metric("📉 Low", f"{latest['low']:.1f}")
                
                with metric_col4:
                    if 'volume' in forex_data.columns:
                        st.metric("📊 Volume", f"{format_number(int(latest['volume']))}")
                    else:
                        st.metric("📊 Volume", "N/A")
                
                with metric_col5:
                    change_symbol = "📈" if change >= 0 else "📉"
                    st.metric(f"{change_symbol} Change", f"{change_pct:+.2f}%")
                
                with metric_col6:
                    # Show range (High - Low)
                    range_val = latest['high'] - latest['low']
                    range_pct = (range_val / latest['close'] * 100) if latest['close'] != 0 else 0
                    st.metric("📏 Range", f"{range_val:.1f} ({range_pct:.1f}%)")
            
            # === ADVANCED FOREX CHART ===
            chart_config = create_chart_config(advanced_controls)
            fig = create_advanced_forex_chart(
                df=forex_data, 
                title=chart_title,
                chart_type=chart_type,
                show_volume=show_volume,
                custom_config=None
            )
            
            # Display chart with advanced config
            st.plotly_chart(fig, use_container_width=True, config=chart_config, key=f"advanced_chart_{chart_type}_{timeframe}")
            
            # === EXPORT FUNCTIONALITY ===
            if hasattr(st.session_state, 'show_export') and st.session_state.show_export:
                with st.expander("💾 Export Chart Data", expanded=True):
                    export_col1, export_col2, export_col3 = st.columns(3)
                    
                    with export_col1:
                        # JSON Export
                        if st.button("📄 Export as JSON"):
                            export_href = export_chart_data(forex_data, f"{chart_type}_chart")
                            if export_href:
                                filename = f"forex_data_{timeframe}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                                st.markdown(
                                    f'<a href="{export_href}" download="{filename}">⬇️ Download JSON Data</a>',
                                    unsafe_allow_html=True
                                )
                                st.success("✅ Export link ready!")
                    
                    with export_col2:
                        # CSV Export
                        if st.button("📊 Export as CSV"):
                            csv_data = forex_data.to_csv(index=False)
                            b64 = base64.b64encode(csv_data.encode()).decode()
                            href = f'data:text/csv;base64,{b64}'
                            filename = f"forex_data_{timeframe}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                            st.markdown(
                                f'<a href="{href}" download="{filename}">⬇️ Download CSV Data</a>',
                                unsafe_allow_html=True
                            )
                            st.success("✅ CSV export ready!")
                    
                    with export_col3:
                        # Chart Settings Export
                        if st.button("⚙️ Export Settings"):
                            settings_data = {
                                "chart_settings": {
                                    "chart_type": chart_type,
                                    "timeframe": timeframe,
                                    "show_volume": show_volume,
                                    "advanced_controls": advanced_controls,
                                    "data_limit": data_limit,
                                    "custom_date_range": str(custom_date_range) if custom_date_range else None,
                                    "market": selected_market,
                                    "export_timestamp": datetime.now().isoformat()
                                }
                            }
                            
                            json_str = json.dumps(settings_data, indent=2)
                            b64 = base64.b64encode(json_str.encode()).decode()
                            href = f'data:application/json;base64,{b64}'
                            filename = f"chart_settings_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                            st.markdown(
                                f'<a href="{href}" download="{filename}">⬇️ Download Settings</a>',
                                unsafe_allow_html=True
                            )
                            st.success("✅ Settings exported!")
                    
                    if st.button("❌ Close Export"):
                        st.session_state.show_export = False
                        st.rerun()
            
            # === CHART ANALYSIS INFO ===
            with st.expander("📊 Chart Analysis & Data Info", expanded=False):
                analysis_col1, analysis_col2 = st.columns(2)
                
                with analysis_col1:
                    st.markdown("### 📈 Current Configuration")
                    st.write(f"**Chart Type:** {chart_type.capitalize()}")
                    st.write(f"**Timeframe:** {timeframe}")
                    st.write(f"**Data Points:** {len(forex_data)}")
                    st.write(f"**Volume Display:** {'✅' if show_volume else '❌'}")
                    st.write(f"**Advanced Controls:** {'✅' if advanced_controls else '❌'}")
                    
                    if custom_date_range:
                        st.write(f"**Custom Range:** {custom_date_range[0]} to {custom_date_range[1]}")
                
                with analysis_col2:
                    st.markdown("### 🎯 Trading Features Available")
                    st.write("✅ **Multiple Chart Types** (Candlestick, Line, OHLC, Area)")
                    st.write("✅ **Custom Date Range Selection**")
                    st.write("✅ **Volume Analysis**")
                    st.write("✅ **Advanced Zoom & Pan Controls**")
                    st.write("✅ **Real-time Data Export** (JSON/CSV)")
                    st.write("✅ **Professional Forex Styling**")
                    st.write("✅ **Drawing Tools** (when enabled)")
                    st.write("✅ **Chart Save & Export**")
    
    except Exception as e:
        st.error(f"❌ Lỗi tạo advanced chart: {e}")
        logging.error(f"Advanced forex chart error: {e}")
        
        # Fallback info
        st.info("""
        **Troubleshooting:**
        - Kiểm tra kết nối database
        - Thử giảm số lượng data points
        - Chọn timeframe khác
        - Liên hệ admin nếu vấn đề vẫn tại
        """)
    
    # Simple info
    with st.expander("💡 Chart Info", expanded=False):
        st.markdown("""
        **Chart Types:** Candlestick, Line, OHLC, Area  
        **Timeframes:** 5T, 15T, 30T, 1H, 2H, 4H, 8H, 1D  
        **Data:** OHLC from likes, Volume from comments
        """)


if __name__ == "__main__":
    main()
